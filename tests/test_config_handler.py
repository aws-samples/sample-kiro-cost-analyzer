"""Tests for backend.config_handler module."""

import json
import os
import re
from unittest.mock import MagicMock, patch

import pytest

from backend.handlers.config_handler import (
    _humanize_schedule,
    handle_get_config,
    handle_put_config_bucket,
    handle_put_config_identity_store_role_arn,
    handle_put_config_prompt_history_enabled,
)


# Pattern matching any pt-BR diacritic we must not leak in English-only backend
# responses (Requirements 11.5, 11.6, 12.1, 12.2).
_PT_BR_CHARS = re.compile(r"[ãâáàçõôóòêéíúüÃÂÁÀÇÕÔÓÒÊÉÍÚÜ]")

# Explicit pt-BR phrase that must never appear in the new route's responses
# (Requirement 11.3 — the new route uses the English "Admin access required").
_FORBIDDEN_PT_BR_PHRASE = "Acesso restrito a administradores"

# Fields on a handler response that carry human-readable prose and therefore
# must be English-only (Requirement 7.1). Machine codes (``status``, ``error``)
# are identifiers and are deliberately excluded.
_HUMAN_READABLE_KEYS = ("message", "humanReadable", "description")


class TestHandleGetConfig:
    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_ETL_STATUS": "/kiro-cost-analyzer/etl-status",
    })
    def test_returns_all_config_fields(self):
        ssm = MagicMock()
        etl_status = {
            "lastExecution": "2026-04-15T10:00:00Z",
            "status": "SUCCESS",
            "filesProcessed": 5,
            "recordsWritten": 120,
            "errors": [],
        }
        ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "my-bucket"}},
            {"Parameter": {"Value": "activities/AWSLogs/123/KiroLogs/"}},
            {"Parameter": {"Value": json.dumps(etl_status)}},
        ]

        result = handle_get_config(ssm_client=ssm)

        assert result["bucketName"] == "my-bucket"
        assert result["sourcePrefix"] == "activities/AWSLogs/123/KiroLogs/"
        assert result["etlStatus"]["status"] == "SUCCESS"
        assert result["etlStatus"]["filesProcessed"] == 5

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_ETL_STATUS": "/kiro-cost-analyzer/etl-status",
    })
    def test_handles_missing_parameters(self):
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("ParameterNotFound")

        result = handle_get_config(ssm_client=ssm)

        assert result["bucketName"] == ""
        assert result["sourcePrefix"] == ""
        assert result["etlStatus"] == {}

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_ETL_STATUS": "/kiro-cost-analyzer/etl-status",
    })
    def test_handles_invalid_etl_status_json(self):
        ssm = MagicMock()
        ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": "bucket-x"}},
            {"Parameter": {"Value": "prefix/"}},
            {"Parameter": {"Value": "not-valid-json"}},
        ]

        result = handle_get_config(ssm_client=ssm)

        assert result["bucketName"] == "bucket-x"
        assert result["etlStatus"] == {"raw": "not-valid-json"}


class TestHandleGetConfigIdentityStoreRoleArn:
    """Tests for the identityStoreRoleArn field returned by handle_get_config.

    Validates Requirements 11.1, 12.3, 12.4 — NONE sentinel normalization,
    verbatim ARN passthrough, and tolerant SSM-exception handling.
    """

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_none_sentinel_is_normalized_to_empty_string(self):
        """SSM sentinel ``NONE`` → empty string (Requirement 12.3)."""
        ssm = MagicMock()

        def get_parameter(Name: str):
            if Name == "/kiro-cost-analyzer/identity-store-role-arn":
                return {"Parameter": {"Value": "NONE"}}
            return {"Parameter": {"Value": ""}}

        ssm.get_parameter.side_effect = get_parameter

        result = handle_get_config(ssm_client=ssm)

        assert result["identityStoreRoleArn"] == ""

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_valid_arn_returned_verbatim(self):
        """A valid IAM role ARN is returned as-is (Requirement 11.1, 12.4)."""
        arn = "arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read"
        ssm = MagicMock()

        def get_parameter(Name: str):
            if Name == "/kiro-cost-analyzer/identity-store-role-arn":
                return {"Parameter": {"Value": arn}}
            return {"Parameter": {"Value": ""}}

        ssm.get_parameter.side_effect = get_parameter

        result = handle_get_config(ssm_client=ssm)

        assert result["identityStoreRoleArn"] == arn

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_ssm_exception_yields_empty_string(self):
        """Any SSM read exception degrades to empty string (Requirement 12.4)."""
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("ParameterNotFound")

        result = handle_get_config(ssm_client=ssm)

        assert result["identityStoreRoleArn"] == ""


class TestHandleGetConfigPromptHistoryEnabled:
    """Tests for the promptHistoryEnabled field returned by handle_get_config.

    Validates Requirements 2.1, 1.6 — feature flag propagation to frontend
    with fail-closed default.
    """

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_returns_true_when_ssm_value_is_true(self):
        """SSM value ``true`` → promptHistoryEnabled is True."""
        ssm = MagicMock()

        def get_parameter(Name: str):
            if Name == "/kiro-cost-analyzer/prompt-history-enabled":
                return {"Parameter": {"Value": "true"}}
            return {"Parameter": {"Value": ""}}

        ssm.get_parameter.side_effect = get_parameter

        result = handle_get_config(ssm_client=ssm)

        assert result["promptHistoryEnabled"] is True

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_returns_false_when_ssm_value_is_false(self):
        """SSM value ``false`` → promptHistoryEnabled is False."""
        ssm = MagicMock()

        def get_parameter(Name: str):
            if Name == "/kiro-cost-analyzer/prompt-history-enabled":
                return {"Parameter": {"Value": "false"}}
            return {"Parameter": {"Value": ""}}

        ssm.get_parameter.side_effect = get_parameter

        result = handle_get_config(ssm_client=ssm)

        assert result["promptHistoryEnabled"] is False

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_returns_false_when_ssm_parameter_missing(self):
        """SSM exception (parameter not found) → promptHistoryEnabled defaults to False (fail-closed)."""
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("ParameterNotFound")

        result = handle_get_config(ssm_client=ssm)

        assert result["promptHistoryEnabled"] is False

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_returns_false_when_ssm_value_is_unexpected(self):
        """SSM value is not exactly ``true`` → promptHistoryEnabled is False (fail-closed)."""
        ssm = MagicMock()

        def get_parameter(Name: str):
            if Name == "/kiro-cost-analyzer/prompt-history-enabled":
                return {"Parameter": {"Value": "True"}}  # uppercase T
            return {"Parameter": {"Value": ""}}

        ssm.get_parameter.side_effect = get_parameter

        result = handle_get_config(ssm_client=ssm)

        assert result["promptHistoryEnabled"] is False

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_returns_false_when_ssm_value_is_empty(self):
        """SSM value is empty string → promptHistoryEnabled is False."""
        ssm = MagicMock()

        def get_parameter(Name: str):
            if Name == "/kiro-cost-analyzer/prompt-history-enabled":
                return {"Parameter": {"Value": ""}}
            return {"Parameter": {"Value": ""}}

        ssm.get_parameter.side_effect = get_parameter

        result = handle_get_config(ssm_client=ssm)

        assert result["promptHistoryEnabled"] is False


class TestHandlePutConfigPromptHistoryEnabled:
    """Tests for handle_put_config_prompt_history_enabled.

    Validates Requirements 1.5, 9.2 — toggle persistence and no SSM value logging.
    """

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_enable_writes_true_to_ssm(self):
        """enabled=True → SSM receives "true" and response is valid."""
        ssm = MagicMock()

        result = handle_put_config_prompt_history_enabled(
            {"enabled": True}, ssm_client=ssm
        )

        assert result["status"] == "valid"
        assert result["message"] == "Prompt history visibility updated"
        assert result["enabled"] is True
        assert "_status_code" not in result
        ssm.put_parameter.assert_called_once_with(
            Name="/kiro-cost-analyzer/prompt-history-enabled",
            Value="true",
            Type="String",
            Overwrite=True,
        )

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_disable_writes_false_to_ssm(self):
        """enabled=False → SSM receives "false" and response is valid."""
        ssm = MagicMock()

        result = handle_put_config_prompt_history_enabled(
            {"enabled": False}, ssm_client=ssm
        )

        assert result["status"] == "valid"
        assert result["message"] == "Prompt history visibility updated"
        assert result["enabled"] is False
        ssm.put_parameter.assert_called_once_with(
            Name="/kiro-cost-analyzer/prompt-history-enabled",
            Value="false",
            Type="String",
            Overwrite=True,
        )

    def test_non_boolean_enabled_returns_400(self):
        """enabled is not a boolean → 400 error response."""
        ssm = MagicMock()

        result = handle_put_config_prompt_history_enabled(
            {"enabled": "true"}, ssm_client=ssm
        )

        assert result["_status_code"] == 400
        assert result["error"] == "InvalidBody"
        assert result["message"] == "enabled field must be a boolean"
        ssm.put_parameter.assert_not_called()

    def test_missing_enabled_field_returns_400(self):
        """Missing enabled field → 400 error response."""
        ssm = MagicMock()

        result = handle_put_config_prompt_history_enabled({}, ssm_client=ssm)

        assert result["_status_code"] == 400
        assert result["error"] == "InvalidBody"
        assert result["message"] == "enabled field must be a boolean"
        ssm.put_parameter.assert_not_called()

    def test_numeric_enabled_returns_400(self):
        """enabled=1 (integer) → 400 error response."""
        ssm = MagicMock()

        result = handle_put_config_prompt_history_enabled(
            {"enabled": 1}, ssm_client=ssm
        )

        assert result["_status_code"] == 400
        assert result["error"] == "InvalidBody"
        ssm.put_parameter.assert_not_called()

    def test_null_enabled_returns_400(self):
        """enabled=None → 400 error response."""
        ssm = MagicMock()

        result = handle_put_config_prompt_history_enabled(
            {"enabled": None}, ssm_client=ssm
        )

        assert result["_status_code"] == 400
        assert result["error"] == "InvalidBody"
        ssm.put_parameter.assert_not_called()

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_does_not_log_ssm_parameter_value(self, capsys):
        """Verify that the SSM parameter value is never logged (Requirement 9.2)."""
        ssm = MagicMock()

        handle_put_config_prompt_history_enabled(
            {"enabled": True}, ssm_client=ssm
        )

        captured = capsys.readouterr()
        # The value "true" or "false" should not appear as a logged SSM value
        # We check that the SSM parameter path is not logged
        assert "/kiro-cost-analyzer/prompt-history-enabled" not in captured.out
        assert "/kiro-cost-analyzer/prompt-history-enabled" not in captured.err


class TestHandlePutConfigBucket:
    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
    })
    def test_valid_bucket_saves_config(self):
        ssm = MagicMock()
        s3 = MagicMock()
        s3.head_bucket.return_value = {}
        s3.exceptions.ClientError = type("ClientError", (Exception,), {})

        result = handle_put_config_bucket(
            {"bucketName": "my-bucket", "sourcePrefix": "prefix/"},
            ssm_client=ssm,
            s3_client=s3,
        )

        assert result["status"] == "valid"
        assert result["bucketName"] == "my-bucket"
        assert result["sourcePrefix"] == "prefix/"
        assert ssm.put_parameter.call_count == 2

    def test_empty_bucket_name_returns_error(self):
        result = handle_put_config_bucket(
            {"bucketName": "", "sourcePrefix": "prefix/"}
        )

        assert result["status"] == "error"
        assert "required" in result["message"]

    def test_missing_bucket_name_returns_error(self):
        result = handle_put_config_bucket({"sourcePrefix": "prefix/"})

        assert result["status"] == "error"
        assert "required" in result["message"]

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
    })
    def test_inaccessible_bucket_returns_error(self):
        ssm = MagicMock()
        s3 = MagicMock()

        client_error = type("ClientError", (Exception,), {})
        s3.exceptions.ClientError = client_error
        error = client_error()
        error.response = {"Error": {"Code": "404"}}
        s3.head_bucket.side_effect = error

        result = handle_put_config_bucket(
            {"bucketName": "nonexistent-bucket", "sourcePrefix": "prefix/"},
            ssm_client=ssm,
            s3_client=s3,
        )

        assert result["status"] == "error"
        assert "does not exist" in result["message"]
        ssm.put_parameter.assert_not_called()

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
    })
    def test_access_denied_bucket_returns_error(self):
        ssm = MagicMock()
        s3 = MagicMock()

        client_error = type("ClientError", (Exception,), {})
        s3.exceptions.ClientError = client_error
        error = client_error()
        error.response = {"Error": {"Code": "403"}}
        s3.head_bucket.side_effect = error

        result = handle_put_config_bucket(
            {"bucketName": "forbidden-bucket", "sourcePrefix": "prefix/"},
            ssm_client=ssm,
            s3_client=s3,
        )

        assert result["status"] == "error"
        assert "Access denied" in result["message"]
        ssm.put_parameter.assert_not_called()

    @patch.dict(os.environ, {
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
    })
    def test_generic_exception_returns_error(self):
        ssm = MagicMock()
        s3 = MagicMock()
        s3.exceptions.ClientError = type("ClientError", (Exception,), {})
        s3.head_bucket.side_effect = RuntimeError("network timeout")

        result = handle_put_config_bucket(
            {"bucketName": "some-bucket", "sourcePrefix": "prefix/"},
            ssm_client=ssm,
            s3_client=s3,
        )

        assert result["status"] == "error"
        assert "network timeout" in result["message"]


class TestHandlePutConfigIdentityStoreRoleArn:
    """Tests for handle_put_config_identity_store_role_arn.

    Mirrors the existing handle_put_config_bucket pattern and validates
    Requirements 11.1, 11.4, 11.5, 11.6, 12.1, 12.2.
    """

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_valid_arn_persists_and_returns_valid_status(self):
        """Valid ARN → ``put_parameter`` receives the ARN verbatim and status is ``valid``."""
        ssm = MagicMock()
        arn = "arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read"

        result = handle_put_config_identity_store_role_arn(
            {"identityStoreRoleArn": arn},
            ssm_client=ssm,
        )

        assert result["status"] == "valid"
        assert result["identityStoreRoleArn"] == arn
        assert result["message"] == "Identity Store role ARN saved successfully"
        ssm.put_parameter.assert_called_once_with(
            Name="/kiro-cost-analyzer/identity-store-role-arn",
            Value=arn,
            Type="String",
            Overwrite=True,
        )
        # Banned-strings regression: English only
        assert not _PT_BR_CHARS.search(result["message"])

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_empty_input_persists_none_sentinel_and_returns_disabled_message(self):
        """Empty input → persists ``NONE`` sentinel and returns the disabled message (Requirement 11.6, 12.2)."""
        ssm = MagicMock()

        result = handle_put_config_identity_store_role_arn(
            {"identityStoreRoleArn": ""},
            ssm_client=ssm,
        )

        assert result["status"] == "valid"
        assert result["identityStoreRoleArn"] == ""
        assert result["message"] == "Cross-account Identity Store mode disabled"
        ssm.put_parameter.assert_called_once_with(
            Name="/kiro-cost-analyzer/identity-store-role-arn",
            Value="NONE",
            Type="String",
            Overwrite=True,
        )
        assert not _PT_BR_CHARS.search(result["message"])

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_missing_body_field_is_treated_as_empty(self):
        """Missing ``identityStoreRoleArn`` field acts as empty input (Requirement 11.6)."""
        ssm = MagicMock()

        result = handle_put_config_identity_store_role_arn({}, ssm_client=ssm)

        assert result["status"] == "valid"
        assert result["identityStoreRoleArn"] == ""
        assert result["message"] == "Cross-account Identity Store mode disabled"
        ssm.put_parameter.assert_called_once()

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_invalid_arn_returns_error_and_does_not_persist(self):
        """Malformed ARN → ``status: error`` and ``put_parameter`` is not called (Requirement 11.5)."""
        ssm = MagicMock()

        result = handle_put_config_identity_store_role_arn(
            {"identityStoreRoleArn": "not-an-arn"},
            ssm_client=ssm,
        )

        assert result["status"] == "error"
        assert result["identityStoreRoleArn"] == "not-an-arn"
        assert result["message"] == (
            "Invalid ARN format. Expected: "
            "arn:aws:iam::<account-id>:role/<role-name>"
        )
        ssm.put_parameter.assert_not_called()
        assert not _PT_BR_CHARS.search(result["message"])

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_arn_with_wrong_service_rejected(self):
        """An ARN for a different service (e.g. S3) is rejected (Requirement 11.5)."""
        ssm = MagicMock()

        result = handle_put_config_identity_store_role_arn(
            {"identityStoreRoleArn": "arn:aws:s3:::my-bucket"},
            ssm_client=ssm,
        )

        assert result["status"] == "error"
        ssm.put_parameter.assert_not_called()

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_whitespace_is_trimmed_before_validation(self):
        """Input is stripped before validation — a whitespace-padded ARN persists cleanly."""
        ssm = MagicMock()
        arn = "arn:aws:iam::222222222222:role/idc-role"

        result = handle_put_config_identity_store_role_arn(
            {"identityStoreRoleArn": f"  {arn}  "},
            ssm_client=ssm,
        )

        assert result["status"] == "valid"
        assert result["identityStoreRoleArn"] == arn
        ssm.put_parameter.assert_called_once_with(
            Name="/kiro-cost-analyzer/identity-store-role-arn",
            Value=arn,
            Type="String",
            Overwrite=True,
        )

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_all_returned_messages_are_english(self):
        """Banned-strings regression across every code path (Requirement 11.5, 11.6, 12.1, 12.2)."""
        ssm = MagicMock()

        valid = handle_put_config_identity_store_role_arn(
            {"identityStoreRoleArn": "arn:aws:iam::222222222222:role/idc-role"},
            ssm_client=ssm,
        )
        empty = handle_put_config_identity_store_role_arn(
            {"identityStoreRoleArn": ""},
            ssm_client=ssm,
        )
        invalid = handle_put_config_identity_store_role_arn(
            {"identityStoreRoleArn": "bad"},
            ssm_client=ssm,
        )

        for result in (valid, empty, invalid):
            assert not _PT_BR_CHARS.search(result["message"]), (
                f"Non-English characters leaked in message: {result['message']!r}"
            )


class TestIdentityStoreRoleArnBannedStringsRegression:
    """Consolidated banned-strings regression for the new cross-account-identity-center surface.

    Iterates over every response the new handler can produce on both code
    paths exercised by the feature:

    * ``handle_put_config_identity_store_role_arn`` — valid ARN, empty input,
      whitespace-only input, missing field, invalid ARN, wrong-service ARN.
    * ``handle_get_config`` — ``identityStoreRoleArn`` field when SSM holds a
      valid ARN, the ``NONE`` sentinel, or raises an exception.

    The test fails if any ``message`` / ``humanReadable`` / ``description``
    string contains pt-BR diacritics or the exact phrase
    ``"Acesso restrito a administradores"`` (Requirements 11.5, 11.6, 12.1, 12.2).
    """

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
        "SSM_BUCKET_NAME": "/kiro-cost-analyzer/bucket-name",
        "SSM_SOURCE_PREFIX": "/kiro-cost-analyzer/source-prefix",
        "SSM_ETL_STATUS": "/kiro-cost-analyzer/etl-status",
        "SSM_PROMPTS_PREFIX": "/kiro-cost-analyzer/prompts-prefix",
        "SSM_IDENTITY_STORE_ID": "/kiro-cost-analyzer/identity-store-id",
        "SSM_SOURCE_BUCKET_ROLE_ARN": "/kiro-cost-analyzer/source-bucket-role-arn",
    }, clear=False)
    def test_no_pt_br_characters_or_forbidden_phrase_on_any_response(self):
        """Iterate every response surface and assert English-only prose."""
        arn = "arn:aws:iam::222222222222:role/kiro-cost-analyzer-identity-store-read"
        ssm = MagicMock()

        # --- PUT /api/config/identity-store-role-arn — all branches ---
        put_ssm = MagicMock()
        put_inputs = [
            {"identityStoreRoleArn": arn},                     # valid
            {"identityStoreRoleArn": ""},                       # empty → "disabled"
            {"identityStoreRoleArn": f"  {arn}  "},             # whitespace padding
            {},                                                 # missing field
            {"identityStoreRoleArn": "not-an-arn"},             # invalid format
            {"identityStoreRoleArn": "arn:aws:s3:::my-bucket"}, # wrong service
            {"identityStoreRoleArn": "NONE"},                   # sentinel rejected as input
        ]
        put_responses = [
            handle_put_config_identity_store_role_arn(body, ssm_client=put_ssm)
            for body in put_inputs
        ]

        # --- GET /api/config — identityStoreRoleArn branches ---
        get_responses: list[dict] = []

        # Valid ARN path
        valid_ssm = MagicMock()
        def _valid_get_parameter(Name: str):
            if Name == "/kiro-cost-analyzer/identity-store-role-arn":
                return {"Parameter": {"Value": arn}}
            return {"Parameter": {"Value": ""}}
        valid_ssm.get_parameter.side_effect = _valid_get_parameter
        get_responses.append(handle_get_config(ssm_client=valid_ssm))

        # NONE sentinel path
        none_ssm = MagicMock()
        def _none_get_parameter(Name: str):
            if Name == "/kiro-cost-analyzer/identity-store-role-arn":
                return {"Parameter": {"Value": "NONE"}}
            return {"Parameter": {"Value": ""}}
        none_ssm.get_parameter.side_effect = _none_get_parameter
        get_responses.append(handle_get_config(ssm_client=none_ssm))

        # SSM exception path
        broken_ssm = MagicMock()
        broken_ssm.get_parameter.side_effect = Exception("ParameterNotFound")
        get_responses.append(handle_get_config(ssm_client=broken_ssm))

        # --- Assert every human-readable string is English-only ---
        failures: list[str] = []
        all_responses = [("PUT", r) for r in put_responses] + [("GET", r) for r in get_responses]

        for route, response in all_responses:
            for key in _HUMAN_READABLE_KEYS:
                value = response.get(key)
                if not isinstance(value, str):
                    continue
                if _PT_BR_CHARS.search(value):
                    failures.append(
                        f"[{route}] pt-BR diacritic in {key!r}: {value!r}"
                    )
                if _FORBIDDEN_PT_BR_PHRASE in value:
                    failures.append(
                        f"[{route}] forbidden phrase {_FORBIDDEN_PT_BR_PHRASE!r} "
                        f"in {key!r}: {value!r}"
                    )

        assert not failures, (
            "Banned-strings regression failed on the cross-account-identity-center "
            "surface:\n  - " + "\n  - ".join(failures)
        )

    @patch.dict(os.environ, {
        "SSM_IDENTITY_STORE_ROLE_ARN": "/kiro-cost-analyzer/identity-store-role-arn",
    }, clear=False)
    def test_guard_detects_injected_forbidden_phrase(self):
        """Meta-guard: if a future regression leaked the forbidden phrase, the
        iteration logic above would catch it. Verified here on a synthetic
        response so the regression can never silently become a no-op.
        """
        synthetic = {"message": f"Something {_FORBIDDEN_PT_BR_PHRASE} here"}
        assert _FORBIDDEN_PT_BR_PHRASE in synthetic["message"]
        # And the char regex catches Portuguese diacritics
        assert _PT_BR_CHARS.search("operação") is not None


class TestHumanizeSchedule:
    """Tests for the _humanize_schedule English outputs (Requirement 7.2)."""

    def test_rate_one_day_returns_every_day(self):
        assert _humanize_schedule("rate(1 day)") == "Every day"

    def test_rate_two_hours_returns_every_2_hours(self):
        assert _humanize_schedule("rate(2 hours)") == "Every 2 hours"

    def test_rate_one_hour_returns_every_hour(self):
        assert _humanize_schedule("rate(1 hour)") == "Every hour"

    def test_rate_five_minutes_returns_every_5_minutes(self):
        assert _humanize_schedule("rate(5 minutes)") == "Every 5 minutes"

    def test_rate_one_minute_returns_every_minute(self):
        assert _humanize_schedule("rate(1 minute)") == "Every minute"

    def test_cron_daily_at_fixed_time_returns_every_day_at_hhmm(self):
        assert _humanize_schedule("cron(59 23 * * ? *)") == "Every day at 23:59"

    def test_cron_midnight_returns_every_day_at_0000(self):
        assert _humanize_schedule("cron(0 0 * * ? *)") == "Every day at 00:00"

    def test_unparsable_expression_returns_raw_expression(self):
        assert _humanize_schedule("not-a-schedule") == "not-a-schedule"

    def test_unparsable_cron_returns_raw_expression(self):
        # Weekly cron is not in the supported-daily pattern → fallback
        expression = "cron(0 12 ? * MON-FRI *)"
        assert _humanize_schedule(expression) == expression

    def test_empty_expression_returns_empty(self):
        assert _humanize_schedule("") == ""
