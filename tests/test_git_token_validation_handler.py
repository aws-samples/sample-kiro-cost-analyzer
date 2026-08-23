"""Tests for backend.handlers.git_token_validation_handler.

No test in this module touches the network: the handler takes an injected
``requests_module``, and the one place that resolves DNS
(``_assert_public_https_host``) is exercised either against literal IPs,
which resolve locally, or against a patched ``getaddrinfo``.
"""

from __future__ import annotations

import json
import logging
import socket
from unittest.mock import patch

import boto3
import pytest
import requests
from moto import mock_aws

from backend.handlers import git_token_validation_handler as handler

TABLE_NAME = "Analytics_Table"
SENTINEL_TOKEN = "ghp_SENTINELtokenVALUE0123456789"

# A public address the SSRF gate must accept, used whenever a GitLab test
# needs the gate to pass without depending on real DNS.
_PUBLIC_ADDRINFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for requests.Response — only the status line is read."""

    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeRequests:
    """Recording stub for the requests module.

    ``statuses`` is consumed one entry per call, in check order. An entry may
    be an int (returned as a status code) or an exception instance (raised).
    """

    RequestException = requests.RequestException

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self._statuses:
            raise AssertionError("unexpected extra request")
        outcome = self._statuses.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _FakeResponse(outcome)

    @property
    def urls(self) -> list[str]:
        return [call["url"] for call in self.calls]


@pytest.fixture
def public_dns():
    """Make every hostname resolve to a public address."""
    with patch.object(socket, "getaddrinfo", return_value=_PUBLIC_ADDRINFO):
        yield


def _github_body(token: str = SENTINEL_TOKEN) -> dict:
    return {
        "url": "https://github.com/vsbatista/agentic-city",
        "provider": "github",
        "accessToken": token,
    }


def _gitlab_body(token: str = SENTINEL_TOKEN) -> dict:
    return {
        "url": "https://gitlab.example.com/group/subgroup/dlt-v2",
        "provider": "gitlab",
        "accessToken": token,
    }


def _statuses(result: dict) -> dict[str, str]:
    return {check["id"]: check["status"] for check in result["checks"]}


# ---------------------------------------------------------------------------
# Check table — the regression guard against drifting from the agent tools
# ---------------------------------------------------------------------------


class TestGithubCheckTable:
    def test_probes_the_three_agent_operations(self):
        fake = _FakeRequests([200, 200, 200])
        result = handler.handle_validate_token(_github_body(), requests_module=fake)

        assert [check["id"] for check in result["checks"]] == [
            "repo_access",
            "commits",
            "pull_requests",
        ]
        assert fake.urls == [
            "https://api.github.com/repos/vsbatista/agentic-city",
            "https://api.github.com/repos/vsbatista/agentic-city/commits",
            "https://api.github.com/repos/vsbatista/agentic-city/pulls",
        ]

    def test_requests_a_single_item_per_listing_check(self):
        fake = _FakeRequests([200, 200, 200])
        handler.handle_validate_token(_github_body(), requests_module=fake)

        assert fake.calls[1]["params"] == {"per_page": 1}
        assert fake.calls[2]["params"] == {"per_page": 1, "state": "all"}

    def test_sends_github_auth_and_accept_headers(self):
        fake = _FakeRequests([200, 200, 200])
        handler.handle_validate_token(_github_body(), requests_module=fake)

        headers = fake.calls[0]["headers"]
        assert headers["Authorization"] == f"token {SENTINEL_TOKEN}"
        assert headers["Accept"] == "application/vnd.github.v3+json"


class TestGitlabCheckTable:
    def test_probes_the_three_agent_operations(self, public_dns):
        fake = _FakeRequests([200, 200, 200])
        result = handler.handle_validate_token(_gitlab_body(), requests_module=fake)

        assert result["overall"] == "ok"
        encoded = "group%2Fsubgroup%2Fdlt-v2"
        assert fake.urls == [
            f"https://gitlab.example.com/api/v4/projects/{encoded}",
            f"https://gitlab.example.com/api/v4/projects/{encoded}/repository/commits",
            f"https://gitlab.example.com/api/v4/projects/{encoded}/merge_requests",
        ]

    def test_sends_private_token_header(self, public_dns):
        fake = _FakeRequests([200, 200, 200])
        handler.handle_validate_token(_gitlab_body(), requests_module=fake)

        assert fake.calls[0]["headers"] == {"PRIVATE-TOKEN": SENTINEL_TOKEN}


# ---------------------------------------------------------------------------
# The incident this feature exists to make self-diagnosing
# ---------------------------------------------------------------------------


class TestIncidentScenario:
    def test_metadata_only_token_reports_contents_and_pulls_missing(self):
        """The 2026-08-23 signature: metadata reads fine, commits are 403.

        A fine-grained PAT with only "Read access to administration and
        metadata" produced a repository that showed "Token configured" and
        silently never correlated.
        """
        fake = _FakeRequests([200, 403, 403])
        result = handler.handle_validate_token(_github_body(), requests_module=fake)

        assert result["overall"] == "partial"
        assert _statuses(result) == {
            "repo_access": "ok",
            "commits": "forbidden",
            "pull_requests": "forbidden",
        }
        assert result["requiredPermissions"] == ["contents:read", "pull_requests:read"]

    def test_every_check_runs_even_after_an_early_failure(self):
        """One round trip must surface the whole picture, not just the first
        broken permission."""
        fake = _FakeRequests([401, 403, 200])
        result = handler.handle_validate_token(_github_body(), requests_module=fake)

        assert len(fake.calls) == 3
        assert _statuses(result) == {
            "repo_access": "unauthorized",
            "commits": "forbidden",
            "pull_requests": "ok",
        }
        assert result["overall"] == "partial"


# ---------------------------------------------------------------------------
# Verdicts and status mapping
# ---------------------------------------------------------------------------


class TestVerdicts:
    def test_all_ok_needs_no_permissions(self):
        fake = _FakeRequests([200, 200, 200])
        result = handler.handle_validate_token(_github_body(), requests_module=fake)

        assert result["overall"] == "ok"
        assert result["requiredPermissions"] == []
        assert result["tokenMissing"] is False

    def test_nothing_ok_is_failed(self):
        fake = _FakeRequests([401, 401, 401])
        result = handler.handle_validate_token(_github_body(), requests_module=fake)

        assert result["overall"] == "failed"
        assert result["requiredPermissions"] == [
            "metadata:read",
            "contents:read",
            "pull_requests:read",
        ]

    def test_empty_listing_is_a_pass(self):
        """A repository with no commits and no PRs still returns 200 — that is
        authorization succeeding, not a permission failure."""
        fake = _FakeRequests([200, 200, 200])
        result = handler.handle_validate_token(_github_body(), requests_module=fake)

        assert _statuses(result) == {
            "repo_access": "ok",
            "commits": "ok",
            "pull_requests": "ok",
        }

    def test_gitlab_deduplicates_its_single_scope(self, public_dns):
        fake = _FakeRequests([403, 403, 403])
        result = handler.handle_validate_token(_gitlab_body(), requests_module=fake)

        assert result["requiredPermissions"] == ["read_api"]


class TestStatusMapping:
    @pytest.mark.parametrize(
        "code,expected",
        [
            (200, "ok"),
            (204, "ok"),
            (401, "unauthorized"),
            (403, "forbidden"),
            (404, "not_found"),
            (429, "rate_limited"),
            (500, "error"),
            (302, "error"),
        ],
    )
    def test_maps_http_status_to_slug(self, code, expected):
        assert handler._status_for(code) == expected

    def test_network_failure_is_unreachable_without_a_status(self):
        fake = _FakeRequests([requests.RequestException("boom"), 200, 200])
        result = handler.handle_validate_token(_github_body(), requests_module=fake)

        assert result["checks"][0] == {
            "id": "repo_access",
            "status": "unreachable",
            "httpStatus": None,
        }

    def test_observed_status_is_reported(self):
        fake = _FakeRequests([200, 403, 429])
        result = handler.handle_validate_token(_github_body(), requests_module=fake)

        assert [check["httpStatus"] for check in result["checks"]] == [200, 403, 429]


# ---------------------------------------------------------------------------
# SSRF containment
# ---------------------------------------------------------------------------


class TestSsrfContainment:
    @pytest.mark.parametrize(
        "url",
        [
            "http://gitlab.example.com/group/project",
            "https://127.0.0.1/group/project",
            "https://169.254.169.254/group/project",
            "https://10.0.0.5/group/project",
            "https://192.168.1.10/group/project",
            "https://[::1]/group/project",
        ],
    )
    def test_rejects_non_public_gitlab_targets_without_probing(self, url):
        fake = _FakeRequests([200, 200, 200])
        result = handler.handle_validate_token(
            {"url": url, "provider": "gitlab", "accessToken": SENTINEL_TOKEN},
            requests_module=fake,
        )

        assert result["_status_code"] == 400
        assert result["error"] == "ValidationError"
        assert fake.calls == []

    def test_rejects_unresolvable_host_without_probing(self):
        fake = _FakeRequests([200, 200, 200])
        with patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("nope")):
            result = handler.handle_validate_token(_gitlab_body(), requests_module=fake)

        assert result["_status_code"] == 400
        assert fake.calls == []

    def test_link_local_blocks_the_metadata_endpoint_by_resolution_too(self):
        """A public-looking hostname that resolves to IMDS is still refused."""
        imds = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))]
        fake = _FakeRequests([200, 200, 200])
        with patch.object(socket, "getaddrinfo", return_value=imds):
            result = handler.handle_validate_token(_gitlab_body(), requests_module=fake)

        assert result["_status_code"] == 400
        assert fake.calls == []

    def test_github_host_is_pinned_regardless_of_submitted_url(self):
        """The submitted URL contributes owner/repo only — never the host."""
        fake = _FakeRequests([200, 200, 200])
        handler.handle_validate_token(
            {
                "url": "https://evil.example/vsbatista/agentic-city",
                "provider": "github",
                "accessToken": SENTINEL_TOKEN,
            },
            requests_module=fake,
        )

        assert fake.calls
        assert all(url.startswith("https://api.github.com/") for url in fake.urls)

    def test_every_call_sets_a_timeout_and_refuses_redirects(self):
        fake = _FakeRequests([200, 200, 200])
        handler.handle_validate_token(_github_body(), requests_module=fake)

        for call in fake.calls:
            assert call["allow_redirects"] is False
            assert isinstance(call["timeout"], (int, float))
            assert call["timeout"] > 0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    @pytest.mark.parametrize("field", ["url", "provider", "accessToken"])
    def test_missing_required_field_is_rejected(self, field):
        fake = _FakeRequests([])
        body = _github_body()
        body[field] = ""
        result = handler.handle_validate_token(body, requests_module=fake)

        assert result["_status_code"] == 400
        assert result["error"] == "ValidationError"
        assert fake.calls == []

    def test_absent_body_is_rejected(self):
        result = handler.handle_validate_token({}, requests_module=_FakeRequests([]))
        assert result["_status_code"] == 400

    @pytest.mark.parametrize("provider", ["bitbucket", "codecommit", "svn", ""])
    def test_unsupported_provider_is_rejected(self, provider):
        fake = _FakeRequests([])
        body = _github_body()
        body["provider"] = provider
        result = handler.handle_validate_token(body, requests_module=fake)

        assert result["_status_code"] == 400
        assert fake.calls == []

    @pytest.mark.parametrize(
        "url",
        ["not-a-url", "ftp://github.com/a/b", "https://github.com", "https://"],
    )
    def test_unparseable_url_is_rejected(self, url):
        fake = _FakeRequests([])
        body = _github_body()
        body["url"] = url
        result = handler.handle_validate_token(body, requests_module=fake)

        assert result["_status_code"] == 400
        assert fake.calls == []


# ---------------------------------------------------------------------------
# Stored-token path
# ---------------------------------------------------------------------------


@pytest.fixture
def stored_repo_env(monkeypatch):
    """DynamoDB + SSM with one registered GitHub repository."""
    monkeypatch.setenv("ANALYTICS_TABLE", TABLE_NAME)
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.Table(TABLE_NAME).put_item(
            Item={
                "PK": "GITREPO#efa4ed67",
                "SK": "CONFIG",
                "name": "Agentic city",
                "url": "https://github.com/vsbatista/agentic-city",
                "provider": "github",
                "ssmTokenPath": "/kiro-cost-analyzer/git-tokens/efa4ed67",
                "status": "ACTIVE",
            }
        )
        ssm = boto3.client("ssm", region_name="us-east-1")
        yield dynamodb, ssm


class TestStoredTokenValidation:
    def test_unknown_repo_is_not_found(self, stored_repo_env):
        dynamodb, ssm = stored_repo_env
        fake = _FakeRequests([])
        result = handler.handle_validate_stored_token(
            "deadbeef",
            dynamodb_resource=dynamodb,
            ssm_client=ssm,
            requests_module=fake,
        )

        assert result["_status_code"] == 404
        assert result["error"] == "NotFound"
        assert fake.calls == []

    def test_absent_token_reports_missing_without_probing(self, stored_repo_env):
        """Probing anonymously would report a public repository as passing —
        exactly the false green this feature prevents."""
        dynamodb, ssm = stored_repo_env
        fake = _FakeRequests([200, 200, 200])
        result = handler.handle_validate_stored_token(
            "efa4ed67",
            dynamodb_resource=dynamodb,
            ssm_client=ssm,
            requests_module=fake,
        )

        assert result["tokenMissing"] is True
        assert result["overall"] == "failed"
        assert _statuses(result) == {
            "repo_access": "unauthorized",
            "commits": "unauthorized",
            "pull_requests": "unauthorized",
        }
        assert fake.calls == []

    def test_stored_token_is_probed_against_the_stored_coordinates(
        self, stored_repo_env
    ):
        dynamodb, ssm = stored_repo_env
        ssm.put_parameter(
            Name="/kiro-cost-analyzer/git-tokens/efa4ed67",
            Value=SENTINEL_TOKEN,
            Type="SecureString",
        )
        fake = _FakeRequests([200, 403, 403])
        result = handler.handle_validate_stored_token(
            "efa4ed67",
            dynamodb_resource=dynamodb,
            ssm_client=ssm,
            requests_module=fake,
        )

        assert result["tokenMissing"] is False
        assert result["overall"] == "partial"
        assert result["requiredPermissions"] == ["contents:read", "pull_requests:read"]
        assert fake.urls[0] == "https://api.github.com/repos/vsbatista/agentic-city"
        assert fake.calls[0]["headers"]["Authorization"] == f"token {SENTINEL_TOKEN}"


# ---------------------------------------------------------------------------
# Credential non-disclosure
# ---------------------------------------------------------------------------


class TestCredentialNonDisclosure:
    def test_token_appears_in_neither_response_nor_logs(self, caplog):
        fake = _FakeRequests([200, 403, requests.RequestException("boom")])
        with caplog.at_level(logging.DEBUG):
            result = handler.handle_validate_token(
                _github_body(), requests_module=fake
            )

        serialized = json.dumps(result)
        assert SENTINEL_TOKEN not in serialized

        emitted = "\n".join(record.getMessage() for record in caplog.records)
        assert SENTINEL_TOKEN not in emitted

    def test_error_body_never_carries_the_token(self):
        body = _github_body()
        body["url"] = "not-a-url"
        result = handler.handle_validate_token(body, requests_module=_FakeRequests([]))

        assert SENTINEL_TOKEN not in json.dumps(result)


# ---------------------------------------------------------------------------
# Correctness properties (design.md properties 1-3)
# ---------------------------------------------------------------------------

_STATUS_CODES = [200, 204, 401, 403, 404, 429, 500]


class TestCorrectnessProperties:
    @pytest.mark.parametrize("first", _STATUS_CODES)
    @pytest.mark.parametrize("second", _STATUS_CODES)
    def test_totality_and_determinism(self, first, second):
        """Property 1 (check totality) and property 2 (verdict determinism)
        over an exhaustive grid of upstream status combinations."""
        for third in _STATUS_CODES:
            fake = _FakeRequests([first, second, third])
            result = handler.handle_validate_token(
                _github_body(), requests_module=fake
            )

            # Property 1: exactly three checks, in CHECK_ORDER.
            assert [c["id"] for c in result["checks"]] == list(handler.CHECK_ORDER)

            # Property 2: overall is a pure function of the status multiset.
            statuses = [c["status"] for c in result["checks"]]
            if all(s == "ok" for s in statuses):
                assert result["overall"] == "ok"
            elif any(s == "ok" for s in statuses):
                assert result["overall"] == "partial"
            else:
                assert result["overall"] == "failed"
            assert result["overall"] in {"ok", "partial", "failed"}

            # Property 3: permissions are exactly those of failing checks,
            # duplicate-free, in CHECK_ORDER first-seen order.
            expected: list[str] = []
            for check in result["checks"]:
                if check["status"] == "ok":
                    continue
                permission = handler.REQUIRED_PERMISSION["github"][check["id"]]
                if permission not in expected:
                    expected.append(permission)
            assert result["requiredPermissions"] == expected
