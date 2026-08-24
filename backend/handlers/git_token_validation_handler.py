"""Git token permission validation.

Probes the exact provider API operations the correlation agent depends on,
using either a token supplied in the request body (before it is saved) or
the token already stored in SSM for a registered repository, and reports a
per-operation verdict plus the permission identifiers needed to fix any
failure.

Motivation: a token can authenticate successfully and still lack the
permissions the agent needs. A fine-grained GitHub PAT carrying only
"administration and metadata" reads a repository's metadata fine, gets 403
on its commits, and produces a repository that shows "Token configured" in
Settings yet silently never appears in a correlation result. That failure
was previously only visible in the AgentCore runtime's CloudWatch logs.

The check table below MIRRORS the operations in
``agent/app/GitCorrelationAgent/tools/github_tool.py`` and
``gitlab_tool.py``. If an operation is added there, add a matching check
here, or validation will report a green token the agent then fails on.

Security notes:
    - The token is never logged, never echoed in a response, and never
      persisted by this module.
    - GitHub requests always go to the ``GITHUB_API_BASE`` constant; the
      submitted URL only contributes ``owner``/``repo`` path segments.
    - GitLab's base URL is necessarily user-supplied, so it is gated to
      https hosts that resolve exclusively to public addresses before any
      socket is opened. This is what stops the endpoint from being used to
      read the instance metadata service from inside the Lambda.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import quote, urlsplit

import boto3
import requests

try:
    from git_shared.git_providers import SSM_TOKEN_PATH_PREFIX, SUPPORTED_PROVIDERS
    from git_shared.git_repository import GitRepository
    from git_shared.git_url_parser import parse_repo_url
except ImportError:  # pragma: no cover - exercised by the Lambda runtime path
    from layers.shared.git_shared.git_providers import (
        SSM_TOKEN_PATH_PREFIX,
        SUPPORTED_PROVIDERS,
    )
    from layers.shared.git_shared.git_repository import GitRepository
    from layers.shared.git_shared.git_url_parser import parse_repo_url

from shared.structured_logger import StructuredLogger

logger = StructuredLogger("git-token-validation")

# --- Check identifiers -------------------------------------------------

CHECK_REPO_ACCESS = "repo_access"
CHECK_COMMITS = "commits"
CHECK_PULL_REQUESTS = "pull_requests"

CHECK_ORDER: tuple[str, ...] = (
    CHECK_REPO_ACCESS,
    CHECK_COMMITS,
    CHECK_PULL_REQUESTS,
)

# Stable permission identifiers surfaced for a failing check. These are
# machine identifiers, not prose: the frontend renders them with each
# provider's own naming.
#
# GitLab is mapped per-endpoint rather than collapsed to a single scope.
# An earlier revision assumed `read_api` gated all three operations; a live
# probe with a restricted token disproved that — it returned 200 on
# merge_requests (so `read_api` was present) while returning 403 on
# commits, because repository CONTENT is gated by `read_repository`, which
# `read_api` does not include.
REQUIRED_PERMISSION: dict[str, dict[str, str]] = {
    "github": {
        CHECK_REPO_ACCESS: "metadata:read",
        CHECK_COMMITS: "contents:read",
        CHECK_PULL_REQUESTS: "pull_requests:read",
    },
    "gitlab": {
        CHECK_REPO_ACCESS: "read_api",
        CHECK_COMMITS: "read_repository",
        CHECK_PULL_REQUESTS: "read_api",
    },
}

# --- Provider endpoints ------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"
_GITHUB_ACCEPT = "application/vnd.github.v3+json"
_GITLAB_API_PATH = "/api/v4"

_REQUEST_TIMEOUT_SECONDS = 10

_STATUS_BY_CODE = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    429: "rate_limited",
}


class _ValidationInputError(Exception):
    """Raised when the request cannot be turned into a safe probe.

    Carries a human-readable English message for the HTTP 400 body. The
    message never contains the token.
    """


def _status_for(http_status: int) -> str:
    """Map an observed HTTP status to a stable check status slug."""
    if 200 <= http_status < 300:
        return "ok"
    return _STATUS_BY_CODE.get(http_status, "error")


def _assert_public_https_host(base_url: str) -> None:
    """Reject a GitLab base URL that is not https or is not public.

    Runs before any socket is opened. ``is_link_local`` is what blocks the
    instance metadata endpoint (169.254.169.254), so the Lambda cannot be
    induced into reading its own role credentials; ``is_private`` covers
    RFC 1918 and fc00::/7.

    Known limitation: the hostname is resolved here and resolved again by
    ``requests`` when connecting, so a DNS entry that changes between the
    two is not defeated. Closing that requires pinning the vetted address
    into the connection, which breaks SNI for legitimate self-hosted
    GitLab instances. Documented in the spec's design.md.

    Args:
        base_url: The GitLab instance base URL (scheme://host[:port]).

    Raises:
        _ValidationInputError: On a non-https scheme, a missing host, a
            resolution failure, or any non-public resolved address.
    """
    parts = urlsplit(base_url)

    if parts.scheme != "https":
        raise _ValidationInputError("provider base URL must use https")

    host = parts.hostname
    if not host:
        raise _ValidationInputError("provider base URL has no host")

    try:
        port = parts.port or 443
    except ValueError:
        raise _ValidationInputError("provider base URL has an invalid port")

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise _ValidationInputError("provider host could not be resolved")

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_private
            or address.is_reserved
            or address.is_unspecified
            or address.is_multicast
        ):
            raise _ValidationInputError(
                "provider host resolves to a non-public address"
            )


def _build_check_requests(provider: str, location: dict) -> list[tuple[str, str, dict]]:
    """Build the (check_id, url, params) triples to probe for a provider.

    GitHub URLs are built against the GITHUB_API_BASE constant — the
    submitted URL only ever contributes path segments, so a hostile host in
    the configured URL cannot redirect the probe. GitLab project paths are
    percent-encoded whole, matching how gitlab_tool.py addresses projects
    by path.

    Args:
        provider: "github" or "gitlab".
        location: The RepoLocation from parse_repo_url.

    Returns:
        One triple per check, ordered by CHECK_ORDER.
    """
    if provider == "github":
        owner = quote(str(location.get("owner", "")), safe="")
        repo = quote(str(location.get("repo", "")), safe="")
        base = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        return [
            (CHECK_REPO_ACCESS, base, {}),
            (CHECK_COMMITS, f"{base}/commits", {"per_page": 1}),
            (CHECK_PULL_REQUESTS, f"{base}/pulls", {"per_page": 1, "state": "all"}),
        ]

    base_url = str(location.get("baseUrl", "")).rstrip("/")
    project = quote(str(location.get("projectPath", "")), safe="")
    base = f"{base_url}{_GITLAB_API_PATH}/projects/{project}"
    return [
        (CHECK_REPO_ACCESS, base, {}),
        (CHECK_COMMITS, f"{base}/repository/commits", {"per_page": 1}),
        (CHECK_PULL_REQUESTS, f"{base}/merge_requests", {"per_page": 1, "state": "all"}),
    ]


def _auth_headers(provider: str, token: str) -> dict:
    """Build the provider auth headers, mirroring the agent's tools."""
    if provider == "github":
        return {"Authorization": f"token {token}", "Accept": _GITHUB_ACCEPT}
    return {"PRIVATE-TOKEN": token}


def _unauthorized_checks() -> list[dict]:
    """Every check reported as unauthorized, with no request performed."""
    return [
        {"id": check_id, "status": "unauthorized", "httpStatus": None}
        for check_id in CHECK_ORDER
    ]


def _run_checks(
    provider: str,
    location: dict,
    token: str,
    requests_module=None,
) -> list[dict]:
    """Probe every operation the correlation agent depends on.

    Requests run sequentially: three calls at a few hundred milliseconds
    each finish well inside the function's timeout, and a thread pool would
    add failure modes for no user-visible gain. Every check runs even after
    an earlier one fails, so the user sees the complete picture in one round
    trip instead of fixing one permission at a time.

    The response body is never read, so it can never reach a log. Only the
    status line matters — an empty 200 (a repository with no commits or no
    pull requests) is a pass, not a failure.

    Args:
        provider: "github" or "gitlab".
        location: The RepoLocation from parse_repo_url.
        token: The access token to probe with. Never logged.
        requests_module: Injected for testability; defaults to ``requests``.

    Returns:
        One result dict per check: {id, status, httpStatus}.

    Raises:
        _ValidationInputError: When the GitLab host fails the safety gate.
    """
    http = requests_module or requests

    if provider == "gitlab":
        _assert_public_https_host(str(location.get("baseUrl", "")))

    headers = _auth_headers(provider, token)
    results: list[dict] = []

    for check_id, url, params in _build_check_requests(provider, location):
        try:
            response = http.get(
                url,
                headers=headers,
                params=params,
                timeout=_REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            # Only the exception class name is recorded: a requests
            # exception's string form can embed the request headers, and
            # those carry the token.
            logger.error(
                "Validation check could not reach the provider",
                checkId=check_id,
                provider=provider,
                errorType=type(exc).__name__,
            )
            results.append({"id": check_id, "status": "unreachable", "httpStatus": None})
            continue

        status_code = int(getattr(response, "status_code", 0) or 0)
        results.append(
            {
                "id": check_id,
                "status": _status_for(status_code),
                "httpStatus": status_code,
            }
        )

    return results


def _summarize(provider: str, checks: list[dict]) -> tuple[str, list[str]]:
    """Derive the overall verdict and the permissions still to be granted.

    Args:
        provider: "github" or "gitlab".
        checks: The per-check results.

    Returns:
        (overall, requiredPermissions) — the permission list is
        duplicate-free and preserves CHECK_ORDER first-seen order.
    """
    statuses = [check["status"] for check in checks]

    if statuses and all(status == "ok" for status in statuses):
        overall = "ok"
    elif any(status == "ok" for status in statuses):
        overall = "partial"
    else:
        overall = "failed"

    permission_map = REQUIRED_PERMISSION.get(provider, {})
    required: list[str] = []
    for check in checks:
        if check["status"] == "ok":
            continue
        permission = permission_map.get(check["id"])
        if permission and permission not in required:
            required.append(permission)

    return overall, required


def _validation_response(
    provider: str,
    checks: list[dict],
    token_missing: bool = False,
) -> dict:
    """Assemble the response contract from per-check results."""
    overall, required = _summarize(provider, checks)
    return {
        "provider": provider,
        "overall": overall,
        "tokenMissing": token_missing,
        "checks": checks,
        "requiredPermissions": required,
    }


def _error(message: str, status_code: int, error: str = "ValidationError") -> dict:
    """Build an error body using the router's _status_code convention."""
    return {"error": error, "message": message, "_status_code": status_code}


def _resolve_location(provider: str, url: str) -> dict:
    """Parse a repository URL into provider location fields.

    Raises:
        _ValidationInputError: When the provider is unsupported or the URL
            cannot be parsed into the provider's coordinates.
    """
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise _ValidationInputError(
            f"Unsupported provider for validation. Supported providers: {supported}"
        )

    location = parse_repo_url(provider, url)
    if location is None:
        raise _ValidationInputError("Repository URL could not be parsed")

    return location


def handle_validate_token(body: dict, requests_module=None) -> dict:
    """Validate a token supplied in the request body, before it is saved.

    The token is probed and discarded — this handler writes nothing to SSM,
    nothing to DynamoDB, and nothing to a log.

    Args:
        body: Request body with url, provider, and accessToken.
        requests_module: Injected for testability.

    Returns:
        The validation response, or an error body carrying _status_code.
    """
    body = body or {}
    url = str(body.get("url", "") or "").strip()
    provider = str(body.get("provider", "") or "").strip()
    access_token = str(body.get("accessToken", "") or "").strip()

    if not url:
        return _error("Repository URL is required", 400)
    if not provider:
        return _error("Provider is required", 400)
    if not access_token:
        return _error("Access token is required", 400)

    try:
        location = _resolve_location(provider, url)
        checks = _run_checks(provider, location, access_token, requests_module)
    except _ValidationInputError as exc:
        return _error(str(exc), 400)

    response = _validation_response(provider, checks)
    logger.info(
        "Ad-hoc token validation completed",
        provider=provider,
        overall=response["overall"],
        checkStatuses={check["id"]: check["status"] for check in checks},
    )
    return response


def handle_validate_stored_token(
    repo_id: str,
    dynamodb_resource=None,
    ssm_client=None,
    requests_module=None,
) -> dict:
    """Validate the token already stored in SSM for a registered repository.

    Accepts no token from the caller: it validates exactly what is
    deployed, so a passing result is trustworthy. When no token is stored,
    every check is reported as unauthorized WITHOUT any outbound request —
    probing anonymously would report a public repository's endpoints as
    passing, which is precisely the false green this feature exists to
    prevent.

    Args:
        repo_id: The stored repository identifier.
        dynamodb_resource: Injected for testability.
        ssm_client: Injected for testability.
        requests_module: Injected for testability.

    Returns:
        The validation response, or an error body carrying _status_code.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "")
    repo_store = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    config = repo_store.get_repo_config(repo_id)
    if not config:
        return _error("Repository not found", 404, error="NotFound")

    provider = str(config.get("provider", "") or "").strip()
    url = str(config.get("url", "") or "").strip()

    try:
        location = _resolve_location(provider, url)
    except _ValidationInputError as exc:
        return _error(str(exc), 400)

    ssm_token_path = str(
        config.get("ssmTokenPath") or f"{SSM_TOKEN_PATH_PREFIX}/{repo_id}"
    )
    token = _read_stored_token(ssm_token_path, ssm_client)

    if not token:
        response = _validation_response(
            provider, _unauthorized_checks(), token_missing=True
        )
        logger.info(
            "Stored token validation found no token",
            repoId=repo_id,
            provider=provider,
            overall=response["overall"],
        )
        return response

    try:
        checks = _run_checks(provider, location, token, requests_module)
    except _ValidationInputError as exc:
        return _error(str(exc), 400)

    response = _validation_response(provider, checks)
    logger.info(
        "Stored token validation completed",
        repoId=repo_id,
        provider=provider,
        overall=response["overall"],
        checkStatuses={check["id"]: check["status"] for check in checks},
    )
    return response


def _read_stored_token(parameter_name: str, ssm_client=None) -> str:
    """Read a SecureString token from SSM, returning "" when absent.

    Never raises and never logs the value. An absent or unreadable
    parameter is indistinguishable from an empty one to the caller, which
    is the correct behaviour: both mean "there is no usable token".
    """
    client = ssm_client or boto3.client("ssm")
    try:
        response = client.get_parameter(Name=parameter_name, WithDecryption=True)
    except Exception as exc:
        logger.info(
            "Stored token parameter is unavailable",
            errorType=type(exc).__name__,
        )
        return ""
    return str(response.get("Parameter", {}).get("Value", "") or "")
