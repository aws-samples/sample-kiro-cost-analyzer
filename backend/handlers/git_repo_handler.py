"""Handler for Git repository CRUD operations.

Provides functions for creating, listing, and deleting Git repository
configurations. Tokens are stored in SSM Parameter Store (SecureString)
and never exposed in DynamoDB or API responses.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import boto3

try:
    from git_shared.git_repository import GitRepository
except ImportError:
    from layers.shared.git_shared.git_repository import GitRepository
try:
    from git_shared.git_providers import SUPPORTED_PROVIDERS
except ImportError:
    from layers.shared.git_shared.git_providers import SUPPORTED_PROVIDERS
from shared.structured_logger import StructuredLogger


logger = StructuredLogger("git-repo-handler")

_SSM_TOKEN_PATH_PREFIX = "/kiro-cost-analyzer/git-tokens"  # noqa: S105 — SSM path prefix, not a secret
_URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


def _validate_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    return bool(_URL_PATTERN.match(url))


def _generate_repo_id() -> str:
    return uuid.uuid4().hex[:8]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def handle_create_repo(
    body: dict,
    claims: dict,
    dynamodb_resource=None,
    ssm_client=None,
) -> dict:
    """Handle POST /api/git/repos — create a new Git repository configuration.

    Security: access tokens are stored in SSM SecureString and NEVER returned
    in any API response. Only a boolean `tokenConfigured` flag is exposed.
    """
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    provider = (body.get("provider") or "").strip().lower()
    access_token = (body.get("accessToken") or "").strip()

    missing = []
    if not name:
        missing.append("name")
    if not url:
        missing.append("url")
    if not provider:
        missing.append("provider")
    if not access_token:
        missing.append("accessToken")
    if missing:
        return {
            "error": "ValidationError",
            "message": f"Missing required fields: {', '.join(missing)}",
            "_status_code": 400,
        }

    # Security: reject tokens that are too short (likely invalid) or too long (potential injection)
    if len(access_token) < 10 or len(access_token) > 500:
        return {
            "error": "ValidationError",
            "message": "Access token must be between 10 and 500 characters.",
            "_status_code": 400,
        }

    if not _validate_url(url):
        return {
            "error": "ValidationError",
            "message": f"Invalid URL: {url}",
            "_status_code": 400,
        }

    if provider not in SUPPORTED_PROVIDERS:
        return {
            "error": "ValidationError",
            "message": f"Unsupported provider: {provider}. Valid providers: {', '.join(sorted(SUPPORTED_PROVIDERS))}",
            "_status_code": 400,
        }

    repo_id = _generate_repo_id()
    ssm_token_path = f"{_SSM_TOKEN_PATH_PREFIX}/{repo_id}"

    ssm = ssm_client or boto3.client("ssm")
    try:
        ssm.put_parameter(
            Name=ssm_token_path,
            Value=access_token,
            Type="SecureString",
            Overwrite=True,
        )
    except Exception as exc:
        logger.error("Failed to store token in SSM", repoId=repo_id, errorType=type(exc).__name__)
        return {
            "error": "InternalError",
            "message": "Failed to store access token.",
            "_status_code": 500,
        }

    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    created_at = _now_iso()
    created_by = claims.get("userId", "")

    config = {
        "name": name,
        "url": url,
        "provider": provider,
        "ssmTokenPath": ssm_token_path,
        "status": "ACTIVE",
        "createdAt": created_at,
        "createdBy": created_by,
    }

    try:
        repo.put_repo_config(repo_id, config)
    except Exception as exc:
        logger.error("Failed to persist repo config; rolling back SSM", repoId=repo_id)
        try:
            ssm.delete_parameter(Name=ssm_token_path)
        except Exception:
            pass
        return {
            "error": "InternalError",
            "message": "Failed to persist repository configuration.",
            "_status_code": 500,
        }

    # `url` deliberately omitted: it can carry internal hostnames, project
    # or organization names, or other topology details that should not
    # appear in logs. repoId is sufficient to look the config up.
    logger.info("Git repository created", repoId=repo_id, provider=provider)

    return {
        "repoId": repo_id,
        "name": name,
        "url": url,
        "provider": provider,
        "tokenConfigured": True,
        "status": "ACTIVE",
        "createdAt": created_at,
        "_status_code": 201,
    }


def handle_list_repos(dynamodb_resource=None) -> dict:
    """Handle GET /api/git/repos — list configured repositories.

    Security: never exposes ssmTokenPath or token values. Only returns
    a boolean `tokenConfigured` flag.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    configs = repo.list_repo_configs()

    repositories = []
    for cfg in configs:
        pk = cfg.get("PK", "")
        repo_id = pk.replace("GITREPO#", "") if pk.startswith("GITREPO#") else ""
        repositories.append({
            "repoId": repo_id,
            "name": cfg.get("name", ""),
            "url": cfg.get("url", ""),
            "provider": cfg.get("provider", ""),
            "tokenConfigured": bool(cfg.get("ssmTokenPath")),
            "status": cfg.get("status", "ACTIVE"),
            "lastSyncAt": cfg.get("lastSyncAt"),
            "createdAt": cfg.get("createdAt", ""),
            # NOTE: ssmTokenPath, accessToken, and any secret fields are
            # intentionally excluded from this response.
        })

    return {"repositories": repositories}


def handle_delete_repo(
    repo_id: str,
    dynamodb_resource=None,
    ssm_client=None,
) -> dict:
    """Handle DELETE /api/git/repos/{repoId} — remove a repository."""
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    config = repo.get_repo_config(repo_id)
    if not config:
        return {
            "error": "NotFound",
            "message": f"Repository not found: {repo_id}",
            "_status_code": 404,
        }

    ssm_token_path = config.get("ssmTokenPath", "")
    if ssm_token_path:
        ssm = ssm_client or boto3.client("ssm")
        try:
            ssm.delete_parameter(Name=ssm_token_path)
        except Exception:
            pass

    repo.delete_repo_config(repo_id)
    logger.info("Git repository deleted", repoId=repo_id)

    return {"message": f"Repository {repo_id} removed successfully"}


def handle_update_repo(
    repo_id: str,
    body: dict,
    claims: dict,
    dynamodb_resource=None,
    ssm_client=None,
) -> dict:
    """Handle PATCH /api/git/repos/{repoId} — partial update / token rotation.

    Accepts any subset of ``{name, url, provider, accessToken}``. When
    ``accessToken`` is present, the SSM SecureString at the repository's
    existing ``ssmTokenPath`` is overwritten in place (rotation), keeping
    ``repoId`` and the parameter path stable. Metadata fields are updated
    via a targeted UpdateExpression, so ``repoId``, ``createdAt``,
    ``createdBy``, and ``ssmTokenPath`` are never modified.

    The SSM write happens BEFORE the DynamoDB update: a failed token write
    aborts the request with 500 and leaves metadata untouched.

    Args:
        repo_id: Repository identifier from the URL path.
        body: Parsed JSON request body (patch).
        claims: Cognito claims of the caller (admin gate is enforced in the
            dispatcher; claims are accepted here for parity with create).
        dynamodb_resource: Optional boto3 DynamoDB resource (tests).
        ssm_client: Optional boto3 SSM client (tests).

    Returns:
        The updated repository in the same shape as ``handle_list_repos``
        items (``tokenConfigured`` boolean; the token value and
        ``ssmTokenPath`` are never returned), or an error dict with
        ``_status_code``.
    """
    table_name = os.environ.get("ANALYTICS_TABLE", "Analytics_Table")
    repo = GitRepository(table_name, dynamodb_resource=dynamodb_resource)

    config = repo.get_repo_config(repo_id)
    if not config:
        return {
            "error": "NotFound",
            "message": f"Repository not found: {repo_id}",
            "_status_code": 404,
        }

    allowed_fields = {"name", "url", "provider", "accessToken"}
    provided = {k: v for k, v in (body or {}).items() if k in allowed_fields}
    if not provided:
        return {
            "error": "ValidationError",
            "message": "Provide at least one of: name, url, provider, accessToken.",
            "_status_code": 400,
        }

    name = provided.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        return {
            "error": "ValidationError",
            "message": "Name must be a non-empty string.",
            "_status_code": 400,
        }

    url = provided.get("url")
    if url is not None and not _validate_url(url):
        return {
            "error": "ValidationError",
            "message": f"Invalid URL: {url}",
            "_status_code": 400,
        }

    provider = provided.get("provider")
    if provider is not None and provider not in SUPPORTED_PROVIDERS:
        return {
            "error": "ValidationError",
            "message": (
                f"Unsupported provider: {provider}. "
                f"Valid providers: {', '.join(sorted(SUPPORTED_PROVIDERS))}"
            ),
            "_status_code": 400,
        }

    access_token = provided.pop("accessToken", None)
    if access_token is not None:
        # Security: same bounds as create — reject tokens that are too
        # short (likely invalid) or too long (potential injection).
        if not isinstance(access_token, str) or len(access_token) < 10 or len(access_token) > 500:
            return {
                "error": "ValidationError",
                "message": "Access token must be between 10 and 500 characters.",
                "_status_code": 400,
            }
        ssm_token_path = config.get("ssmTokenPath", "")
        if not ssm_token_path:
            # Defensive: a CONFIG item always carries ssmTokenPath (set at
            # create); reuse the deterministic path if it is ever absent.
            ssm_token_path = f"{_SSM_TOKEN_PATH_PREFIX}/{repo_id}"
        ssm = ssm_client or boto3.client("ssm")
        try:
            # Rotation in place: same parameter path, Overwrite=True — the
            # token value is never logged.
            ssm.put_parameter(
                Name=ssm_token_path,
                Value=access_token,
                Type="SecureString",
                Overwrite=True,
            )
        except Exception as exc:
            logger.error(
                "Failed to rotate token in SSM",
                repoId=repo_id,
                errorType=type(exc).__name__,
            )
            return {
                "error": "InternalError",
                "message": "Failed to rotate access token.",
                "_status_code": 500,
            }
        if not config.get("ssmTokenPath"):
            provided["ssmTokenPath"] = ssm_token_path

    if provided:
        try:
            repo.update_repo_config_fields(repo_id, provided)
        except Exception as exc:
            logger.error(
                "Failed to update repo config",
                repoId=repo_id,
                errorType=type(exc).__name__,
            )
            return {
                "error": "InternalError",
                "message": "Failed to update repository configuration.",
                "_status_code": 500,
            }

    updated = repo.get_repo_config(repo_id) or {}
    changed_fields = sorted(list(provided) + (["accessToken"] if access_token else []))
    # NOTE: url is deliberately omitted from the log line (internal hostnames);
    # the token value is never logged.
    logger.info("Git repository updated", repoId=repo_id, fields=changed_fields)

    return {
        "repoId": repo_id,
        "name": updated.get("name", ""),
        "url": updated.get("url", ""),
        "provider": updated.get("provider", ""),
        "tokenConfigured": bool(updated.get("ssmTokenPath")),
        "status": updated.get("status", "ACTIVE"),
        "lastSyncAt": updated.get("lastSyncAt"),
        "createdAt": updated.get("createdAt", ""),
        # NOTE: ssmTokenPath, accessToken, and any secret fields are
        # intentionally excluded from this response.
    }


def handle_manual_sync(repo_id: str, **kwargs) -> dict:
    """Manual sync is no longer supported — agent fetches data on-demand."""
    return {
        "error": "Gone",
        "message": "Manual sync is no longer supported. Analysis is done on-demand by the agent.",
        "_status_code": 410,
    }
