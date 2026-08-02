"""Tests for backend.handler — API Gateway Lambda router."""

import json
import re
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from backend.handler import (
    ADMIN_GROUP,
    _build_response,
    _extract_claims,
    _is_admin,
    lambda_handler,
)


def _make_event(
    method: str = "GET",
    path: str = "/api/usage",
    query_params: dict | None = None,
    body: dict | None = None,
    groups: str = "",
    sub: str = "user-123",
    username: str = "user-123",
) -> dict:
    """Build a minimal API Gateway proxy event."""
    event = {
        "httpMethod": method,
        "path": path,
        "queryStringParameters": query_params,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": sub,
                    "cognito:username": username,
                    "cognito:groups": groups,
                }
            }
        },
    }
    return event


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestExtractClaims:
    def test_extracts_sub_and_groups(self):
        event = _make_event(groups="Admins,Viewers", sub="abc-123", username="admin@example.com")
        claims = _extract_claims(event)
        assert claims["userId"] == "abc-123"
        assert claims["groups"] == ["Admins", "Viewers"]
        assert claims["username"] == "admin@example.com"

    def test_empty_groups(self):
        event = _make_event(groups="", sub="u1")
        claims = _extract_claims(event)
        assert claims["groups"] == []

    def test_missing_authorizer(self):
        event = {"requestContext": {}}
        claims = _extract_claims(event)
        assert claims["userId"] == ""
        assert claims["groups"] == []


class TestIsAdmin:
    def test_admin_in_groups(self):
        assert _is_admin({"groups": [ADMIN_GROUP, "Other"]}) is True

    def test_not_admin(self):
        assert _is_admin({"groups": ["Viewers"]}) is False

    def test_empty_groups(self):
        assert _is_admin({"groups": []}) is False


class TestBuildResponse:
    def test_dict_body(self):
        resp = _build_response(200, {"ok": True})
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"]) == {"ok": True}
        assert resp["headers"]["Content-Type"] == "application/json"
        assert resp["headers"]["Access-Control-Allow-Origin"] == "https://localhost:5173"

    def test_string_body(self):
        resp = _build_response(200, "raw-csv", "text/csv")
        assert resp["body"] == "raw-csv"
        assert resp["headers"]["Content-Type"] == "text/csv"


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------

class TestGetUsage:
    @patch("backend.handler.usage_handler")
    def test_routes_to_usage_handler_admin(self, mock_mod):
        """Admin users see all usage data without userId filter."""
        mock_mod.handle_usage.return_value = {"summary": {}, "users": []}
        event = _make_event("GET", "/api/usage", query_params={"startDate": "2026-01-01"}, groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_usage.assert_called_once_with({"startDate": "2026-01-01"})

    @patch("backend.handler.usage_handler")
    def test_routes_to_usage_handler_non_admin_scoped(self, mock_mod):
        """Non-admin users with kiroUserId are scoped to their own data."""
        mock_mod.handle_usage.return_value = {"summary": {}, "users": []}
        event = _make_event("GET", "/api/usage", query_params={"startDate": "2026-01-01"})
        # Add custom:kiro_user_id to simulate a linked user
        event["requestContext"]["authorizer"]["claims"]["custom:kiro_user_id"] = "kiro-abc-123"
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_usage.assert_called_once_with({"startDate": "2026-01-01", "userId": "kiro-abc-123"})

    def test_non_admin_without_kiro_id_gets_empty(self):
        """Non-admin users without kiroUserId get empty response."""
        event = _make_event("GET", "/api/usage", query_params={"startDate": "2026-01-01"})
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["users"] == []


class TestGetUsageAccount:
    @patch("backend.handler.account_usage_handler")
    def test_routes_to_account_usage_handler(self, mock_mod):
        mock_mod.handle_account_usage.return_value = {"totals": {}}
        event = _make_event("GET", "/api/usage/account", groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_account_usage.assert_called_once_with({})

    def test_non_admin_forbidden(self):
        event = _make_event("GET", "/api/usage/account")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403


class TestGetUsageExport:
    @patch("backend.handler.export_handler")
    def test_csv_export_sets_content_type(self, mock_mod):
        mock_mod.handle_export.return_value = {
            "statusCode": 200,
            "body": "col1,col2\nval1,val2",
            "contentType": "text/csv",
        }
        event = _make_event("GET", "/api/usage/export", query_params={"format": "csv"}, groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        assert resp["headers"]["Content-Type"] == "text/csv"
        assert resp["body"] == "col1,col2\nval1,val2"

    @patch("backend.handler.export_handler")
    def test_json_export(self, mock_mod):
        mock_mod.handle_export.return_value = {
            "statusCode": 200,
            "body": "[{}]",
            "contentType": "application/json",
        }
        event = _make_event("GET", "/api/usage/export", query_params={"format": "json"}, groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        assert resp["headers"]["Content-Type"] == "application/json"

    def test_non_admin_forbidden(self):
        event = _make_event("GET", "/api/usage/export")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403


class TestGetConfig:
    @patch("backend.handler.config_handler")
    def test_routes_to_config_handler(self, mock_mod):
        mock_mod.handle_get_config.return_value = {"bucketName": "b", "sourcePrefix": "p", "etlStatus": {}}
        event = _make_event("GET", "/api/config")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_get_config.assert_called_once()


class TestPutConfigBucket:
    @patch("backend.handler.config_handler")
    def test_admin_can_update_bucket(self, mock_mod):
        mock_mod.handle_put_config_bucket.return_value = {"status": "valid"}
        event = _make_event("PUT", "/api/config/bucket", body={"bucketName": "b"}, groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_put_config_bucket.assert_called_once_with({"bucketName": "b"})

    def test_non_admin_gets_403(self):
        event = _make_event("PUT", "/api/config/bucket", body={"bucketName": "b"}, groups="Viewers")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403
        assert "Forbidden" in json.loads(resp["body"])["error"]


class TestPutConfigIdentityStoreRoleArn:
    """Routing tests for PUT /api/config/identity-store-role-arn.

    Validates Requirements 11.2, 11.3 — admin-gated route and the English
    forbidden message.
    """

    # Pattern catching any pt-BR diacritic in response messages for the new route.
    _PT_BR_CHARS = re.compile(r"[ãâáàçõôóòêéíúüÃÂÁÀÇÕÔÓÒÊÉÍÚÜ]")

    @patch("backend.handler.config_handler")
    def test_admin_gets_200_via_handler(self, mock_mod):
        """Admin caller → 200 and the handler is invoked with the raw body."""
        arn = "arn:aws:iam::222222222222:role/idc-role"
        mock_mod.handle_put_config_identity_store_role_arn.return_value = {
            "identityStoreRoleArn": arn,
            "status": "valid",
            "message": "Identity Store role ARN saved successfully",
        }
        event = _make_event(
            "PUT",
            "/api/config/identity-store-role-arn",
            body={"identityStoreRoleArn": arn},
            groups="Admins",
        )

        resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        mock_mod.handle_put_config_identity_store_role_arn.assert_called_once_with(
            {"identityStoreRoleArn": arn},
        )
        body = json.loads(resp["body"])
        assert body["identityStoreRoleArn"] == arn
        assert body["status"] == "valid"
        assert not self._PT_BR_CHARS.search(body["message"])

    @patch("backend.handler.config_handler")
    def test_non_admin_gets_403_with_english_message_and_handler_not_called(self, mock_mod):
        """Non-admin caller → 403 with English message; handler never runs."""
        event = _make_event(
            "PUT",
            "/api/config/identity-store-role-arn",
            body={"identityStoreRoleArn": "arn:aws:iam::222222222222:role/idc-role"},
            groups="Viewers",
        )

        resp = lambda_handler(event, None)

        assert resp["statusCode"] == 403
        body = json.loads(resp["body"])
        assert body["error"] == "Forbidden"
        assert body["message"] == "Admin access required"
        assert not self._PT_BR_CHARS.search(body["message"])
        mock_mod.handle_put_config_identity_store_role_arn.assert_not_called()

    @patch("backend.handler.config_handler")
    def test_empty_groups_gets_403(self, mock_mod):
        """Caller with no groups → 403, handler is not invoked."""
        event = _make_event(
            "PUT",
            "/api/config/identity-store-role-arn",
            body={"identityStoreRoleArn": ""},
            groups="",
        )

        resp = lambda_handler(event, None)

        assert resp["statusCode"] == 403
        mock_mod.handle_put_config_identity_store_role_arn.assert_not_called()

    @patch("backend.handler.config_handler")
    def test_admin_empty_body_forwarded_to_handler(self, mock_mod):
        """Empty body from an admin is forwarded to the handler (disables cross-account)."""
        mock_mod.handle_put_config_identity_store_role_arn.return_value = {
            "identityStoreRoleArn": "",
            "status": "valid",
            "message": "Cross-account Identity Store mode disabled",
        }
        event = _make_event(
            "PUT",
            "/api/config/identity-store-role-arn",
            body={"identityStoreRoleArn": ""},
            groups="Admins",
        )

        resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        mock_mod.handle_put_config_identity_store_role_arn.assert_called_once_with(
            {"identityStoreRoleArn": ""},
        )
        body = json.loads(resp["body"])
        assert body["message"] == "Cross-account Identity Store mode disabled"
        assert not self._PT_BR_CHARS.search(body["message"])


class TestIdentityStoreRoleArnRouteBannedStringsRegression:
    """Consolidated banned-strings regression for PUT /api/config/identity-store-role-arn.

    Iterates over every response the router can return for the new route —
    the 200 success path (handler result forwarded through ``_build_response``)
    and the 403 non-admin path — and asserts that no ``message`` /
    ``humanReadable`` / ``description`` string contains pt-BR diacritics or
    the exact pt-BR phrase ``"Acesso restrito a administradores"``.

    Requirements: 11.5, 11.6, 12.1, 12.2.
    """

    # Pattern catching any pt-BR diacritic.
    _PT_BR_CHARS = re.compile(r"[ãâáàçõôóòêéíúüÃÂÁÀÇÕÔÓÒÊÉÍÚÜ]")
    # Specific forbidden phrase (Requirement 11.3).
    _FORBIDDEN_PT_BR_PHRASE = "Acesso restrito a administradores"
    _HUMAN_READABLE_KEYS = ("message", "humanReadable", "description")

    @patch("backend.handler.config_handler")
    def test_no_pt_br_in_any_router_response_for_new_route(self, mock_mod):
        """Enumerate every router branch for the new route and check prose."""
        arn = "arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read"

        # Handler-level responses that the router forwards verbatim on 200.
        handler_outputs = [
            # Valid ARN accepted
            {
                "identityStoreRoleArn": arn,
                "status": "valid",
                "message": "Identity Store role ARN saved successfully",
            },
            # Empty input → cross-account disabled
            {
                "identityStoreRoleArn": "",
                "status": "valid",
                "message": "Cross-account Identity Store mode disabled",
            },
            # Invalid ARN → error, but still forwarded with 200 by the router
            {
                "identityStoreRoleArn": "not-an-arn",
                "status": "error",
                "message": (
                    "Invalid ARN format. Expected: "
                    "arn:aws:iam::<account-id>:role/<role-name>"
                ),
            },
        ]

        collected_responses: list[dict] = []

        for handler_output in handler_outputs:
            mock_mod.handle_put_config_identity_store_role_arn.return_value = handler_output
            event = _make_event(
                "PUT",
                "/api/config/identity-store-role-arn",
                body={"identityStoreRoleArn": handler_output["identityStoreRoleArn"]},
                groups="Admins",
            )
            resp = lambda_handler(event, None)
            assert resp["statusCode"] == 200
            collected_responses.append(json.loads(resp["body"]))

        # 403 branches — non-admin and no-group callers.
        for groups in ("Viewers", ""):
            event = _make_event(
                "PUT",
                "/api/config/identity-store-role-arn",
                body={"identityStoreRoleArn": arn},
                groups=groups,
            )
            resp = lambda_handler(event, None)
            assert resp["statusCode"] == 403
            collected_responses.append(json.loads(resp["body"]))

        # Scan every response surface.
        failures: list[str] = []
        for response in collected_responses:
            for key in self._HUMAN_READABLE_KEYS:
                value = response.get(key)
                if not isinstance(value, str):
                    continue
                if self._PT_BR_CHARS.search(value):
                    failures.append(
                        f"pt-BR diacritic in {key!r}: {value!r}"
                    )
                if self._FORBIDDEN_PT_BR_PHRASE in value:
                    failures.append(
                        f"forbidden phrase {self._FORBIDDEN_PT_BR_PHRASE!r} "
                        f"in {key!r}: {value!r}"
                    )

        assert not failures, (
            "Banned-strings regression failed on PUT /api/config/identity-store-role-arn:\n"
            "  - " + "\n  - ".join(failures)
        )


class TestPostEtlTrigger:
    @patch("backend.handler.etl_trigger_handler")
    def test_admin_can_trigger_etl(self, mock_mod):
        mock_mod.handle_etl_trigger.return_value = {"status": "triggered"}
        event = _make_event("POST", "/api/etl/trigger", groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200

    def test_non_admin_gets_403(self):
        event = _make_event("POST", "/api/etl/trigger", groups="")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403


class TestGetUsers:
    @patch("backend.handler.users_handler")
    def test_admin_can_list_users(self, mock_mod):
        mock_mod.handle_list_users.return_value = {"users": []}
        event = _make_event("GET", "/api/users", groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200

    def test_non_admin_gets_403(self):
        event = _make_event("GET", "/api/users", groups="")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403


class TestPostUsers:
    @patch("backend.handler.users_handler")
    def test_admin_can_create_user(self, mock_mod):
        mock_mod.handle_create_user.return_value = {"status": "created"}
        event = _make_event("POST", "/api/users", body={"email": "user@example.com"}, groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_create_user.assert_called_once_with({"email": "user@example.com"})

    def test_non_admin_gets_403(self):
        event = _make_event("POST", "/api/users", body={"email": "user@example.com"}, groups="")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403


class TestDeleteUser:
    @patch("backend.handler.users_handler")
    def test_admin_can_delete_user(self, mock_mod):
        mock_mod.handle_delete_user.return_value = {"status": "disabled", "userId": "target-user"}
        event = _make_event("DELETE", "/api/users/target-user", groups="Admins", username="admin-user")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_delete_user.assert_called_once_with("target-user", "admin-user")

    def test_non_admin_gets_403(self):
        event = _make_event("DELETE", "/api/users/target-user", groups="")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403


class TestUnknownRoute:
    def test_returns_404(self):
        event = _make_event("GET", "/api/nonexistent")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 404
        body = json.loads(resp["body"])
        assert body["error"] == "NotFound"

    def test_post_unknown_returns_404(self):
        event = _make_event("POST", "/api/unknown")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 404


class TestErrorHandling:
    @patch("backend.handler.usage_handler")
    def test_dynamodb_throttling_returns_503(self, mock_mod):
        error_response = {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "Rate exceeded"}}
        mock_mod.handle_usage.side_effect = ClientError(error_response, "Query")
        event = _make_event("GET", "/api/usage", groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 503
        body = json.loads(resp["body"])
        assert body["error"] == "ServiceUnavailable"

    @patch("backend.handler.usage_handler")
    def test_dynamodb_throttling_exception_returns_503(self, mock_mod):
        error_response = {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}
        mock_mod.handle_usage.side_effect = ClientError(error_response, "Query")
        event = _make_event("GET", "/api/usage", groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 503
        body = json.loads(resp["body"])
        assert body["error"] == "ServiceUnavailable"

    @patch("backend.handler.usage_handler")
    def test_other_client_error_returns_500(self, mock_mod):
        error_response = {"Error": {"Code": "ValidationException", "Message": "Bad request"}}
        mock_mod.handle_usage.side_effect = ClientError(error_response, "Query")
        event = _make_event("GET", "/api/usage", groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 500
        body = json.loads(resp["body"])
        assert body["error"] == "InternalError"

    @patch("backend.handler.usage_handler")
    def test_generic_exception_returns_500(self, mock_mod):
        mock_mod.handle_usage.side_effect = RuntimeError("unexpected")
        event = _make_event("GET", "/api/usage", groups="Admins")
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 500
        body = json.loads(resp["body"])
        assert body["error"] == "InternalError"

    def test_invalid_json_body_returns_400(self):
        event = _make_event("POST", "/api/users", groups="Admins")
        event["body"] = "not-json{{"
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "InvalidBody"


class TestPromptsRoute:
    """Tests for ``GET /api/prompts`` and ``GET /api/prompts/{requestId}``.

    Covers admin gating and the self-lookup translation: when the requested
    ``userId`` equals the caller's Cognito sub and the caller has a
    ``custom:kiro_user_id`` claim, the route swaps ``userId`` to the Kiro
    userId before delegating to the prompts handler. PROMPT# items are
    keyed by the Kiro userId, not the Cognito sub.
    """

    @patch("backend.handler.prompts_handler")
    def test_non_admin_forbidden_on_list(self, mock_mod):
        event = _make_event(
            "GET",
            "/api/prompts",
            query_params={"userId": "anyone"},
            groups="Viewers",
        )
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403
        mock_mod.handle_list_prompts.assert_not_called()

    @patch("backend.handler.prompts_handler")
    def test_non_admin_forbidden_on_detail(self, mock_mod):
        event = _make_event(
            "GET",
            "/api/prompts/req-1",
            query_params={"userId": "anyone"},
            groups="Viewers",
        )
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 403
        mock_mod.handle_get_prompt_detail.assert_not_called()

    @patch("backend.handler.prompts_handler")
    def test_admin_self_lookup_translates_to_kiro_user_id(self, mock_mod):
        """Admin querying their own Cognito sub gets translated to Kiro userId."""
        mock_mod.handle_list_prompts.return_value = {"items": [], "nextToken": None}
        event = _make_event(
            "GET",
            "/api/prompts",
            query_params={"userId": "cognito-sub-123", "limit": "20"},
            groups="Admins",
            sub="cognito-sub-123",
        )
        event["requestContext"]["authorizer"]["claims"]["custom:kiro_user_id"] = "kiro-uuid-abc"
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_list_prompts.assert_called_once_with(
            {"userId": "kiro-uuid-abc", "limit": "20"}
        )

    @patch("backend.handler.prompts_handler")
    def test_admin_self_lookup_translates_on_detail(self, mock_mod):
        """Detail route also rewrites the self-lookup userId to the Kiro userId."""
        mock_mod.handle_get_prompt_detail.return_value = {"requestId": "req-1"}
        event = _make_event(
            "GET",
            "/api/prompts/req-1",
            query_params={"userId": "cognito-sub-123"},
            groups="Admins",
            sub="cognito-sub-123",
        )
        event["requestContext"]["authorizer"]["claims"]["custom:kiro_user_id"] = "kiro-uuid-abc"
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_get_prompt_detail.assert_called_once_with(
            "req-1", {"userId": "kiro-uuid-abc"}
        )

    @patch("backend.handler.prompts_handler")
    def test_admin_query_for_other_user_passes_through(self, mock_mod):
        """Admin querying a different userId is unchanged (admins can see anyone)."""
        mock_mod.handle_list_prompts.return_value = {"items": [], "nextToken": None}
        event = _make_event(
            "GET",
            "/api/prompts",
            query_params={"userId": "kiro-uuid-other", "limit": "20"},
            groups="Admins",
            sub="cognito-sub-123",
        )
        event["requestContext"]["authorizer"]["claims"]["custom:kiro_user_id"] = "kiro-uuid-abc"
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_list_prompts.assert_called_once_with(
            {"userId": "kiro-uuid-other", "limit": "20"}
        )

    @patch("backend.handler.prompts_handler")
    def test_admin_self_lookup_without_kiro_claim_passes_through(self, mock_mod):
        """If the admin has no custom:kiro_user_id claim, the userId is unchanged."""
        mock_mod.handle_list_prompts.return_value = {"items": [], "nextToken": None}
        event = _make_event(
            "GET",
            "/api/prompts",
            query_params={"userId": "cognito-sub-123"},
            groups="Admins",
            sub="cognito-sub-123",
        )
        # No custom:kiro_user_id claim set.
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 200
        mock_mod.handle_list_prompts.assert_called_once_with(
            {"userId": "cognito-sub-123"}
        )
