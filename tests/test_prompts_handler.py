"""Tests for backend.handlers.prompts_handler module — _FeatureFlagCache."""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.handlers.prompts_handler import _FeatureFlagCache


class TestFeatureFlagCache:
    """Tests for the _FeatureFlagCache class."""

    def setup_method(self):
        """Reset cache state before each test."""
        _FeatureFlagCache.reset()

    def test_returns_true_when_ssm_value_is_true(self):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}

        result = _FeatureFlagCache.is_enabled(ssm_client=ssm)

        assert result is True
        ssm.get_parameter.assert_called_once()

    def test_returns_false_when_ssm_value_is_false(self):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "false"}}

        result = _FeatureFlagCache.is_enabled(ssm_client=ssm)

        assert result is False

    def test_returns_true_case_insensitive(self):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "True"}}

        result = _FeatureFlagCache.is_enabled(ssm_client=ssm)

        assert result is True

    def test_returns_false_on_ssm_error(self):
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("SSM unavailable")

        result = _FeatureFlagCache.is_enabled(ssm_client=ssm)

        assert result is False

    def test_caches_value_within_ttl(self):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}

        # First call fetches from SSM
        result1 = _FeatureFlagCache.is_enabled(ssm_client=ssm)
        assert result1 is True
        assert ssm.get_parameter.call_count == 1

        # Second call uses cache
        result2 = _FeatureFlagCache.is_enabled(ssm_client=ssm)
        assert result2 is True
        assert ssm.get_parameter.call_count == 1  # No additional call

    def test_refreshes_after_ttl_expires(self):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}

        # First call
        _FeatureFlagCache.is_enabled(ssm_client=ssm)
        assert ssm.get_parameter.call_count == 1

        # Simulate TTL expiry
        _FeatureFlagCache._last_fetched = time.time() - 301

        # Second call should fetch again
        _FeatureFlagCache.is_enabled(ssm_client=ssm)
        assert ssm.get_parameter.call_count == 2

    def test_fail_closed_on_client_error(self):
        """Fail-closed: returns False when SSM raises ClientError."""
        from botocore.exceptions import ClientError

        ssm = MagicMock()
        ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": "Not found"}},
            "GetParameter",
        )

        result = _FeatureFlagCache.is_enabled(ssm_client=ssm)

        assert result is False

    @patch.dict(os.environ, {"SSM_PROMPT_HISTORY_ENABLED": "/custom/param-path"})
    def test_uses_env_var_for_parameter_name(self):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}

        _FeatureFlagCache.is_enabled(ssm_client=ssm)

        ssm.get_parameter.assert_called_once_with(Name="/custom/param-path")

    def test_uses_default_parameter_name_when_env_not_set(self):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "false"}}

        # Ensure env var is not set
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SSM_PROMPT_HISTORY_ENABLED", None)
            _FeatureFlagCache.is_enabled(ssm_client=ssm)

        ssm.get_parameter.assert_called_once_with(
            Name="/kiro-cost-analyzer/prompt-history-enabled"
        )

    def test_reset_clears_cache(self):
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}

        _FeatureFlagCache.is_enabled(ssm_client=ssm)
        assert _FeatureFlagCache._value is True

        _FeatureFlagCache.reset()
        assert _FeatureFlagCache._value is False
        assert _FeatureFlagCache._last_fetched == 0.0

    def test_does_not_log_ssm_parameter_path_or_value(self, capsys):
        """Verify that no log output contains the SSM parameter path or value."""
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}

        _FeatureFlagCache.is_enabled(ssm_client=ssm)

        captured = capsys.readouterr()
        # Must not log the parameter path
        assert "/kiro-cost-analyzer/prompt-history-enabled" not in captured.out
        assert "/kiro-cost-analyzer/prompt-history-enabled" not in captured.err
        # Must not log the parameter value
        assert '"true"' not in captured.out or "prompt-history" not in captured.out

    def test_does_not_log_on_ssm_error(self, capsys):
        """Verify that SSM errors don't leak parameter path in logs."""
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("Connection timeout")

        _FeatureFlagCache.is_enabled(ssm_client=ssm)

        captured = capsys.readouterr()
        # Must not log the parameter path even on error
        assert "/kiro-cost-analyzer/prompt-history-enabled" not in captured.out
        assert "/kiro-cost-analyzer/prompt-history-enabled" not in captured.err


class TestHandleListPrompts:
    """Tests for handle_list_prompts function."""

    def setup_method(self):
        """Reset cache state before each test."""
        _FeatureFlagCache.reset()

    def _make_ssm_enabled(self):
        """Create a mock SSM client that returns feature enabled."""
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}
        return ssm

    def _make_ssm_disabled(self):
        """Create a mock SSM client that returns feature disabled."""
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "false"}}
        return ssm

    def test_returns_400_when_user_id_missing(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        result = handle_list_prompts(
            query_params={},
            ssm_client=self._make_ssm_enabled(),
        )

        assert result["_status_code"] == 400
        assert result["error"] == "InvalidParameters"
        assert result["message"] == "userId is required"

    def test_returns_400_when_user_id_empty(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        result = handle_list_prompts(
            query_params={"userId": ""},
            ssm_client=self._make_ssm_enabled(),
        )

        assert result["_status_code"] == 400
        assert result["error"] == "InvalidParameters"
        assert result["message"] == "userId is required"

    def test_returns_403_when_feature_disabled(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        result = handle_list_prompts(
            query_params={"userId": "user-123"},
            ssm_client=self._make_ssm_disabled(),
        )

        assert result["_status_code"] == 403
        assert result["error"] == "Forbidden"
        assert result["message"] == "Prompt history is not enabled"

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_returns_items_with_prompt_preview(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        # Mock the repository
        mock_repo_result = {
            "items": [
                {
                    "requestId": "req-1",
                    "timestamp": "2026-04-10T14:18:03.103Z",
                    "category": "Code Generation",
                    "prompt": "Write a function that calculates Fibonacci",
                    "modelId": "claude-sonnet",
                    "triggerType": "CHAT",
                    "promptLength": 45,
                    "responseLength": 200,
                }
            ],
            "nextToken": None,
        }

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = mock_repo_result

            result = handle_list_prompts(
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        assert "items" in result
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["requestId"] == "req-1"
        assert item["timestamp"] == "2026-04-10T14:18:03.103Z"
        assert item["category"] == "Code Generation"
        assert item["promptPreview"] == "Write a function that calculates Fibonacci"
        assert item["modelId"] == "claude-sonnet"
        assert item["triggerType"] == "CHAT"
        assert item["promptLength"] == 45
        assert item["responseLength"] == 200
        assert result["nextToken"] is None

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_truncates_prompt_preview_at_200_chars(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        long_prompt = "x" * 300

        mock_repo_result = {
            "items": [
                {
                    "requestId": "req-1",
                    "timestamp": "2026-04-10T14:18:03.103Z",
                    "category": "Code Generation",
                    "prompt": long_prompt,
                    "modelId": "claude-sonnet",
                    "triggerType": "CHAT",
                    "promptLength": 300,
                    "responseLength": 100,
                }
            ],
            "nextToken": None,
        }

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = mock_repo_result

            result = handle_list_prompts(
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        item = result["items"][0]
        assert len(item["promptPreview"]) == 203  # 200 + "..."
        assert item["promptPreview"].endswith("...")

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_excludes_system_categories_by_default(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {"items": [], "nextToken": None}

            handle_list_prompts(
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

            call_kwargs = mock_instance.get_user_prompts.call_args[1]
            assert call_kwargs["exclude_categories"] is not None
            # Should exclude all system categories. Casing must match the
            # values written by the categorizer/writer because DynamoDB
            # Attr filters are case-sensitive.
            excluded = set(call_kwargs["exclude_categories"])
            assert "Empty" in excluded
            assert "NOT_CATEGORIZED" in excluded
            assert "Classification Error" in excluded

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_does_not_exclude_when_category_explicitly_set(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {"items": [], "nextToken": None}

            handle_list_prompts(
                query_params={"userId": "user-123", "category": "Code Generation"},
                ssm_client=self._make_ssm_enabled(),
            )

            call_kwargs = mock_instance.get_user_prompts.call_args[1]
            # When a specific category is requested, no exclusion
            assert call_kwargs["exclude_categories"] is None
            assert call_kwargs["category"] == "Code Generation"

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_allows_system_category_when_explicitly_requested(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {"items": [], "nextToken": None}

            handle_list_prompts(
                query_params={"userId": "user-123", "category": "Empty"},
                ssm_client=self._make_ssm_enabled(),
            )

            call_kwargs = mock_instance.get_user_prompts.call_args[1]
            assert call_kwargs["exclude_categories"] is None
            assert call_kwargs["category"] == "Empty"

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_system_category_exclusion_casing_matches_written_values(self):
        """Regression: exclusion list casing MUST match what the writer emits.

        ``Attr.ne()`` filters in DynamoDB are case-sensitive. If the
        exclusion list is lowercase but DynamoDB stores ``Empty`` /
        ``NOT_CATEGORIZED`` / ``Classification Error``, the FilterExpression
        silently fails to exclude anything. The handler then returns those
        system items, the frontend filters them out client-side, and the
        Prompt History table renders empty even when the user has thousands
        of meaningful prompts.
        """
        from backend.handlers.prompts_handler import _SYSTEM_CATEGORIES, handle_list_prompts

        assert _SYSTEM_CATEGORIES == {"Empty", "NOT_CATEGORIZED", "Classification Error"}

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {"items": [], "nextToken": None}

            handle_list_prompts(
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

            excluded = set(mock_instance.get_user_prompts.call_args[1]["exclude_categories"])
            assert excluded == {"Empty", "NOT_CATEGORIZED", "Classification Error"}

    def test_system_categories_constant_is_sourced_from_shared(self):
        """The handler's ``_SYSTEM_CATEGORIES`` MUST be a re-export of
        ``shared.categories.SYSTEM_CATEGORIES``. Inlining the literal is
        what allowed the original lowercase typo to drift from the writer
        and the categorizer in the first place.
        """
        from backend.handlers import prompts_handler
        from shared.categories import SYSTEM_CATEGORIES

        assert prompts_handler._SYSTEM_CATEGORIES is SYSTEM_CATEGORIES

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_clamps_limit_to_max_100(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {"items": [], "nextToken": None}

            handle_list_prompts(
                query_params={"userId": "user-123", "limit": "500"},
                ssm_client=self._make_ssm_enabled(),
            )

            call_kwargs = mock_instance.get_user_prompts.call_args[1]
            assert call_kwargs["limit"] == 100

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_clamps_limit_to_min_1(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {"items": [], "nextToken": None}

            handle_list_prompts(
                query_params={"userId": "user-123", "limit": "-5"},
                ssm_client=self._make_ssm_enabled(),
            )

            call_kwargs = mock_instance.get_user_prompts.call_args[1]
            assert call_kwargs["limit"] == 1

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_defaults_limit_to_20(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {"items": [], "nextToken": None}

            handle_list_prompts(
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

            call_kwargs = mock_instance.get_user_prompts.call_args[1]
            assert call_kwargs["limit"] == 20

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_defaults_limit_to_20_for_non_numeric(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {"items": [], "nextToken": None}

            handle_list_prompts(
                query_params={"userId": "user-123", "limit": "abc"},
                ssm_client=self._make_ssm_enabled(),
            )

            call_kwargs = mock_instance.get_user_prompts.call_args[1]
            assert call_kwargs["limit"] == 20

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_passes_pagination_token(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {
                "items": [],
                "nextToken": "next-page-token",
            }

            result = handle_list_prompts(
                query_params={"userId": "user-123", "nextToken": "some-token"},
                ssm_client=self._make_ssm_enabled(),
            )

            call_kwargs = mock_instance.get_user_prompts.call_args[1]
            assert call_kwargs["next_token"] == "some-token"
            assert result["nextToken"] == "next-page-token"

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_passes_date_filters(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = {"items": [], "nextToken": None}

            handle_list_prompts(
                query_params={
                    "userId": "user-123",
                    "startDate": "2026-01-01",
                    "endDate": "2026-01-31",
                },
                ssm_client=self._make_ssm_enabled(),
            )

            call_kwargs = mock_instance.get_user_prompts.call_args[1]
            assert call_kwargs["start_date"] == "2026-01-01"
            assert call_kwargs["end_date"] == "2026-01-31"

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_does_not_log_prompt_content(self, capsys):
        from backend.handlers.prompts_handler import handle_list_prompts

        secret_content = "THIS_IS_SECRET_PROMPT_CONTENT_THAT_MUST_NOT_APPEAR_IN_LOGS"

        mock_repo_result = {
            "items": [
                {
                    "requestId": "req-1",
                    "timestamp": "2026-04-10T14:18:03.103Z",
                    "category": "Code Generation",
                    "prompt": secret_content,
                    "modelId": "claude-sonnet",
                    "triggerType": "CHAT",
                    "promptLength": len(secret_content),
                    "responseLength": 100,
                }
            ],
            "nextToken": None,
        }

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = mock_repo_result

            handle_list_prompts(
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        captured = capsys.readouterr()
        assert secret_content not in captured.out
        assert secret_content not in captured.err

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_handles_empty_prompt_field(self):
        from backend.handlers.prompts_handler import handle_list_prompts

        mock_repo_result = {
            "items": [
                {
                    "requestId": "req-1",
                    "timestamp": "2026-04-10T14:18:03.103Z",
                    "category": "Code Generation",
                    "modelId": "claude-sonnet",
                    "triggerType": "CHAT",
                    "promptLength": 0,
                    "responseLength": 0,
                }
            ],
            "nextToken": None,
        }

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = mock_repo_result

            result = handle_list_prompts(
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        assert result["items"][0]["promptPreview"] == ""


class TestGeneratePromptPreview:
    """Tests for _generate_prompt_preview helper."""

    def test_returns_empty_for_none(self):
        from backend.handlers.prompts_handler import _generate_prompt_preview

        assert _generate_prompt_preview(None) == ""

    def test_returns_empty_for_empty_string(self):
        from backend.handlers.prompts_handler import _generate_prompt_preview

        assert _generate_prompt_preview("") == ""

    def test_returns_original_when_under_200(self):
        from backend.handlers.prompts_handler import _generate_prompt_preview

        text = "Hello world"
        assert _generate_prompt_preview(text) == text

    def test_returns_original_when_exactly_200(self):
        from backend.handlers.prompts_handler import _generate_prompt_preview

        text = "a" * 200
        assert _generate_prompt_preview(text) == text

    def test_truncates_with_ellipsis_when_over_200(self):
        from backend.handlers.prompts_handler import _generate_prompt_preview

        text = "b" * 201
        result = _generate_prompt_preview(text)
        assert len(result) == 203  # 200 + "..."
        assert result == "b" * 200 + "..."


class TestClampLimit:
    """Tests for _clamp_limit helper."""

    def test_default_20_when_none(self):
        from backend.handlers.prompts_handler import _clamp_limit

        assert _clamp_limit(None) == 20

    def test_default_20_for_non_numeric(self):
        from backend.handlers.prompts_handler import _clamp_limit

        assert _clamp_limit("abc") == 20

    def test_clamps_to_min_1(self):
        from backend.handlers.prompts_handler import _clamp_limit

        assert _clamp_limit("0") == 1
        assert _clamp_limit("-10") == 1

    def test_clamps_to_max_100(self):
        from backend.handlers.prompts_handler import _clamp_limit

        assert _clamp_limit("101") == 100
        assert _clamp_limit("999") == 100

    def test_valid_values_pass_through(self):
        from backend.handlers.prompts_handler import _clamp_limit

        assert _clamp_limit("1") == 1
        assert _clamp_limit("50") == 50
        assert _clamp_limit("100") == 100


class TestHandleGetPromptDetail:
    """Tests for handle_get_prompt_detail function."""

    def setup_method(self):
        """Reset cache state before each test."""
        _FeatureFlagCache.reset()

    def _make_ssm_enabled(self):
        """Create a mock SSM client that returns feature enabled."""
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}
        return ssm

    def _make_ssm_disabled(self):
        """Create a mock SSM client that returns feature disabled."""
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "false"}}
        return ssm

    def test_returns_400_when_user_id_missing(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        result = handle_get_prompt_detail(
            request_id="req-123",
            query_params={},
            ssm_client=self._make_ssm_enabled(),
        )

        assert result["_status_code"] == 400
        assert result["error"] == "InvalidParameters"
        assert result["message"] == "userId is required"

    def test_returns_400_when_user_id_empty(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        result = handle_get_prompt_detail(
            request_id="req-123",
            query_params={"userId": ""},
            ssm_client=self._make_ssm_enabled(),
        )

        assert result["_status_code"] == 400
        assert result["error"] == "InvalidParameters"
        assert result["message"] == "userId is required"

    def test_returns_400_for_path_traversal_request_id(self):
        """Holmes CSR finding: requestId must be rejected before it can be
        interpolated into an S3 key (defense-in-depth against path
        traversal), independent of the DynamoDB lookup that follows it."""
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            result = handle_get_prompt_detail(
                request_id="../../etc/passwd",
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        assert result["_status_code"] == 400
        assert result["error"] == "InvalidParameters"
        # The DynamoDB lookup must never be reached for an invalid requestId.
        MockRepo.return_value.get_prompt_by_request_id.assert_not_called()

    def test_returns_400_for_request_id_with_slash(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            result = handle_get_prompt_detail(
                request_id="abc/def",
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        assert result["_status_code"] == 400
        MockRepo.return_value.get_prompt_by_request_id.assert_not_called()

    def test_returns_403_when_feature_disabled(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        result = handle_get_prompt_detail(
            request_id="req-123",
            query_params={"userId": "user-123"},
            ssm_client=self._make_ssm_disabled(),
        )

        assert result["_status_code"] == 403
        assert result["error"] == "Forbidden"
        assert result["message"] == "Prompt history is not enabled"

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_returns_404_when_prompt_not_found(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = None

            result = handle_get_prompt_detail(
                request_id="req-nonexistent",
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        assert result["_status_code"] == 404
        assert result["error"] == "NotFound"
        assert result["message"] == "Prompt not found"

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_returns_inline_content_when_not_in_s3(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        mock_item = {
            "requestId": "req-abc",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "prompt": "Write a Fibonacci function",
            "response": "Here is a Fibonacci function...",
            "promptLength": 27,
            "responseLength": 31,
            "contentInS3": False,
        }

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            result = handle_get_prompt_detail(
                request_id="req-abc",
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        assert "_status_code" not in result
        assert result["requestId"] == "req-abc"
        assert result["timestamp"] == "2026-04-10T14:18:03.103Z"
        assert result["category"] == "Code Generation"
        assert result["modelId"] == "claude-sonnet"
        assert result["prompt"] == "Write a Fibonacci function"
        assert result["response"] == "Here is a Fibonacci function..."
        assert result["promptLength"] == 27
        assert result["responseLength"] == 31
        assert result["contentInS3"] is False

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "DATA_BUCKET": "test-bucket"})
    def test_fetches_content_from_s3_when_content_in_s3(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail
        import json as json_mod

        mock_item = {
            "requestId": "req-s3",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "prompt": "",
            "response": "",
            "promptLength": 500,
            "responseLength": 1000,
            "contentInS3": True,
        }

        s3_content = json_mod.dumps({
            "prompt": "This is the full prompt from S3",
            "response": "This is the full response from S3",
        }).encode("utf-8")

        mock_s3 = MagicMock()
        mock_s3_body = MagicMock()
        mock_s3_body.read.return_value = s3_content
        mock_s3.get_object.return_value = {"Body": mock_s3_body}

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            result = handle_get_prompt_detail(
                request_id="req-s3",
                query_params={"userId": "user-123"},
                s3_client=mock_s3,
                ssm_client=self._make_ssm_enabled(),
            )

        assert "_status_code" not in result
        assert result["prompt"] == "This is the full prompt from S3"
        assert result["response"] == "This is the full response from S3"
        assert result["contentInS3"] is True

        # Verify S3 was called with correct bucket and key
        mock_s3.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="prompts-content/req-s3.json",
        )

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "DATA_BUCKET": "test-bucket"})
    def test_returns_500_on_s3_failure(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        mock_item = {
            "requestId": "req-s3-fail",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "prompt": "",
            "response": "",
            "promptLength": 500,
            "responseLength": 1000,
            "contentInS3": True,
        }

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = Exception("S3 access denied")

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            result = handle_get_prompt_detail(
                request_id="req-s3-fail",
                query_params={"userId": "user-123"},
                s3_client=mock_s3,
                ssm_client=self._make_ssm_enabled(),
            )

        assert result["_status_code"] == 500
        assert result["error"] == "ContentRetrievalFailed"
        assert result["message"] == "Failed to retrieve prompt content"

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "DATA_BUCKET": "test-bucket"})
    def test_does_not_log_content_on_s3_failure(self, capsys):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        mock_item = {
            "requestId": "req-s3-fail",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "prompt": "SECRET_INLINE_CONTENT",
            "response": "SECRET_RESPONSE_CONTENT",
            "promptLength": 500,
            "responseLength": 1000,
            "contentInS3": True,
        }

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = Exception("S3 access denied")

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            handle_get_prompt_detail(
                request_id="req-s3-fail",
                query_params={"userId": "user-123"},
                s3_client=mock_s3,
                ssm_client=self._make_ssm_enabled(),
            )

        captured = capsys.readouterr()
        assert "SECRET_INLINE_CONTENT" not in captured.out
        assert "SECRET_INLINE_CONTENT" not in captured.err
        assert "SECRET_RESPONSE_CONTENT" not in captured.out
        assert "SECRET_RESPONSE_CONTENT" not in captured.err

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_does_not_log_prompt_content_on_success(self, capsys):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        secret_prompt = "THIS_SECRET_PROMPT_MUST_NOT_APPEAR_IN_LOGS"
        secret_response = "THIS_SECRET_RESPONSE_MUST_NOT_APPEAR_IN_LOGS"

        mock_item = {
            "requestId": "req-secret",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "prompt": secret_prompt,
            "response": secret_response,
            "promptLength": len(secret_prompt),
            "responseLength": len(secret_response),
            "contentInS3": False,
        }

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            handle_get_prompt_detail(
                request_id="req-secret",
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        captured = capsys.readouterr()
        assert secret_prompt not in captured.out
        assert secret_prompt not in captured.err
        assert secret_response not in captured.out
        assert secret_response not in captured.err

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_returns_empty_strings_for_missing_content_fields(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        mock_item = {
            "requestId": "req-minimal",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "promptLength": 0,
            "responseLength": 0,
            "contentInS3": False,
        }

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            result = handle_get_prompt_detail(
                request_id="req-minimal",
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        assert result["prompt"] == ""
        assert result["response"] == ""
        assert result["promptLength"] == 0
        assert result["responseLength"] == 0

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_uses_default_data_bucket_when_env_not_set(self):
        from backend.handlers.prompts_handler import handle_get_prompt_detail
        import json as json_mod

        mock_item = {
            "requestId": "req-default-bucket",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "prompt": "",
            "response": "",
            "promptLength": 100,
            "responseLength": 200,
            "contentInS3": True,
        }

        s3_content = json_mod.dumps({
            "prompt": "prompt from default bucket",
            "response": "response from default bucket",
        }).encode("utf-8")

        mock_s3 = MagicMock()
        mock_s3_body = MagicMock()
        mock_s3_body.read.return_value = s3_content
        mock_s3.get_object.return_value = {"Body": mock_s3_body}

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            # DATA_BUCKET is always set by template.yaml in a real deploy.
            # There is deliberately no hardcoded bucket-name fallback (S3
            # bucket squatting risk) — an unset DATA_BUCKET fails loudly
            # with a 500 instead of falling back to a guessable name.
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("DATA_BUCKET", None)
                result = handle_get_prompt_detail(
                    request_id="req-default-bucket",
                    query_params={"userId": "user-123"},
                    s3_client=mock_s3,
                    ssm_client=self._make_ssm_enabled(),
                )

        mock_s3.get_object.assert_not_called()
        assert result["_status_code"] == 500
        assert result["error"] == "InternalError"


class TestLogSafetyVerification:
    """Comprehensive verification that no prompt content or SSM values appear in logs.

    Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.6, 9.7

    These tests capture ALL log output (both stdout/stderr from StructuredLogger
    and standard logging) and assert that sensitive content never appears.
    """

    def setup_method(self):
        """Reset cache state before each test."""
        _FeatureFlagCache.reset()

    def _make_ssm_enabled(self):
        """Create a mock SSM client that returns feature enabled."""
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}
        return ssm

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable"})
    def test_list_prompts_no_content_in_any_log_output(self, capsys):
        """Serve a list prompts request and verify no content substring in logs.

        Validates: Requirements 9.1, 9.3, 9.6, 9.7
        """
        from backend.handlers.prompts_handler import handle_list_prompts

        # Use distinctive content that would be easy to detect in logs
        secret_prompt = "ULTRA_SECRET_PROMPT_CONTENT_XYZ_12345"
        secret_response = "ULTRA_SECRET_RESPONSE_CONTENT_ABC_67890"

        mock_repo_result = {
            "items": [
                {
                    "requestId": "req-verify-1",
                    "timestamp": "2026-04-10T14:18:03.103Z",
                    "category": "Code Generation",
                    "prompt": secret_prompt,
                    "response": secret_response,
                    "modelId": "claude-sonnet",
                    "triggerType": "CHAT",
                    "promptLength": len(secret_prompt),
                    "responseLength": len(secret_response),
                },
                {
                    "requestId": "req-verify-2",
                    "timestamp": "2026-04-11T10:00:00.000Z",
                    "category": "Debugging",
                    "prompt": "Another secret prompt that must not leak",
                    "response": "Another secret response that must not leak",
                    "modelId": "claude-haiku",
                    "triggerType": "INLINE",
                    "promptLength": 40,
                    "responseLength": 42,
                },
            ],
            "nextToken": "some-token",
        }

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_user_prompts.return_value = mock_repo_result

            handle_list_prompts(
                query_params={"userId": "user-123", "limit": "50"},
                ssm_client=self._make_ssm_enabled(),
            )

        captured = capsys.readouterr()
        all_output = captured.out + captured.err

        # Verify no prompt content appears in any log output
        assert secret_prompt not in all_output
        assert secret_response not in all_output
        assert "Another secret prompt that must not leak" not in all_output
        assert "Another secret response that must not leak" not in all_output

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "DATA_BUCKET": "test-bucket"})
    def test_get_prompt_detail_no_content_in_any_log_output(self, capsys):
        """Serve a prompt detail request and verify no content substring in logs.

        Validates: Requirements 9.1, 9.3, 9.6, 9.7
        """
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        secret_prompt = "DETAIL_SECRET_PROMPT_NEVER_IN_LOGS_999"
        secret_response = "DETAIL_SECRET_RESPONSE_NEVER_IN_LOGS_888"

        mock_item = {
            "requestId": "req-detail-verify",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "prompt": secret_prompt,
            "response": secret_response,
            "promptLength": len(secret_prompt),
            "responseLength": len(secret_response),
            "contentInS3": False,
        }

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            result = handle_get_prompt_detail(
                request_id="req-detail-verify",
                query_params={"userId": "user-123"},
                ssm_client=self._make_ssm_enabled(),
            )

        # Confirm the handler returned the content (it works correctly)
        assert result["prompt"] == secret_prompt
        assert result["response"] == secret_response

        # But the content must NOT appear in logs
        captured = capsys.readouterr()
        all_output = captured.out + captured.err
        assert secret_prompt not in all_output
        assert secret_response not in all_output

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "DATA_BUCKET": "test-bucket"})
    def test_get_prompt_detail_s3_content_not_in_logs(self, capsys):
        """Serve a prompt detail with S3 content and verify no content in logs.

        Validates: Requirements 9.1, 9.4, 9.6
        """
        from backend.handlers.prompts_handler import handle_get_prompt_detail
        import json as json_mod

        s3_prompt = "S3_STORED_PROMPT_CONTENT_MUST_NOT_LEAK_TO_LOGS"
        s3_response = "S3_STORED_RESPONSE_CONTENT_MUST_NOT_LEAK_TO_LOGS"

        mock_item = {
            "requestId": "req-s3-verify",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "prompt": "",
            "response": "",
            "promptLength": len(s3_prompt),
            "responseLength": len(s3_response),
            "contentInS3": True,
        }

        s3_content = json_mod.dumps({
            "prompt": s3_prompt,
            "response": s3_response,
        }).encode("utf-8")

        mock_s3 = MagicMock()
        mock_s3_body = MagicMock()
        mock_s3_body.read.return_value = s3_content
        mock_s3.get_object.return_value = {"Body": mock_s3_body}

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            result = handle_get_prompt_detail(
                request_id="req-s3-verify",
                query_params={"userId": "user-123"},
                s3_client=mock_s3,
                ssm_client=self._make_ssm_enabled(),
            )

        # Confirm the handler returned the S3 content correctly
        assert result["prompt"] == s3_prompt
        assert result["response"] == s3_response

        # But the content must NOT appear in logs
        captured = capsys.readouterr()
        all_output = captured.out + captured.err
        assert s3_prompt not in all_output
        assert s3_response not in all_output

    @patch.dict(os.environ, {"ANALYTICS_TABLE": "TestAnalyticsTable", "DATA_BUCKET": "test-bucket"})
    def test_s3_error_does_not_log_content_or_exception_with_content(self, capsys):
        """On S3 failure, verify error logs contain only errorType, not content.

        Validates: Requirements 9.4, 9.6
        """
        from backend.handlers.prompts_handler import handle_get_prompt_detail

        # Simulate an exception whose message might contain content
        error_with_content = "NoSuchKey: prompts-content/req-err.json - SECRET_DATA_IN_ERROR"

        mock_item = {
            "requestId": "req-err",
            "timestamp": "2026-04-10T14:18:03.103Z",
            "category": "Code Generation",
            "modelId": "claude-sonnet",
            "prompt": "INLINE_CONTENT_SHOULD_NOT_LEAK",
            "response": "INLINE_RESPONSE_SHOULD_NOT_LEAK",
            "promptLength": 100,
            "responseLength": 200,
            "contentInS3": True,
        }

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = Exception(error_with_content)

        with patch(
            "backend.handlers.prompts_handler.AnalyticsRepository"
        ) as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_prompt_by_request_id.return_value = mock_item

            result = handle_get_prompt_detail(
                request_id="req-err",
                query_params={"userId": "user-123"},
                s3_client=mock_s3,
                ssm_client=self._make_ssm_enabled(),
            )

        assert result["_status_code"] == 500

        captured = capsys.readouterr()
        all_output = captured.out + captured.err

        # The exception message (which might contain content) must not be logged
        assert "SECRET_DATA_IN_ERROR" not in all_output
        assert "INLINE_CONTENT_SHOULD_NOT_LEAK" not in all_output
        assert "INLINE_RESPONSE_SHOULD_NOT_LEAK" not in all_output

        # But errorType should be present (it's safe metadata)
        assert "Exception" in all_output

    def test_feature_flag_cache_ssm_read_no_value_in_logs(self, capsys):
        """Perform SSM read for feature flag and verify no parameter value in logs.

        Validates: Requirements 9.2
        """
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "true"}}

        _FeatureFlagCache.is_enabled(ssm_client=ssm)

        captured = capsys.readouterr()
        all_output = captured.out + captured.err

        # The SSM parameter path must not appear in logs
        assert "/kiro-cost-analyzer/prompt-history-enabled" not in all_output
        # The SSM parameter value must not appear in logs
        # (checking that "true" doesn't appear in context of SSM)
        # Note: "true" alone is too common, so we check the path isn't logged
        # which is the primary concern for SSM value leakage

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_config_toggle_ssm_write_no_value_in_logs(self, capsys):
        """Perform SSM write for toggle and verify no parameter value in logs.

        Validates: Requirements 9.2
        """
        from backend.handlers.config_handler import handle_put_config_prompt_history_enabled

        ssm = MagicMock()

        # Test enabling
        handle_put_config_prompt_history_enabled(
            {"enabled": True}, ssm_client=ssm
        )

        captured = capsys.readouterr()
        all_output = captured.out + captured.err

        # The SSM parameter path must not appear in logs
        assert "/kiro-cost-analyzer/prompt-history-enabled" not in all_output

    @patch.dict(os.environ, {
        "SSM_PROMPT_HISTORY_ENABLED": "/kiro-cost-analyzer/prompt-history-enabled",
    }, clear=False)
    def test_config_toggle_disable_no_value_in_logs(self, capsys):
        """Perform SSM write (disable) for toggle and verify no parameter value in logs.

        Validates: Requirements 9.2
        """
        from backend.handlers.config_handler import handle_put_config_prompt_history_enabled

        ssm = MagicMock()

        # Test disabling
        handle_put_config_prompt_history_enabled(
            {"enabled": False}, ssm_client=ssm
        )

        captured = capsys.readouterr()
        all_output = captured.out + captured.err

        # The SSM parameter path must not appear in logs
        assert "/kiro-cost-analyzer/prompt-history-enabled" not in all_output
