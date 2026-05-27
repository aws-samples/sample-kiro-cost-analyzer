"""Tests for backend.handlers.etl_trigger_handler module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from backend.handlers.etl_trigger_handler import handle_etl_trigger


class TestHandleEtlTrigger:
    @patch.dict(os.environ, {
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:etl-pipeline",
    })
    def test_starts_step_functions_execution_and_returns_triggered(self):
        client = MagicMock()
        client.start_execution.return_value = {
            "executionArn": "arn:aws:states:us-east-1:123456789012:execution:etl-pipeline:exec-123",
            "startDate": "2025-01-15T14:30:25Z",
        }

        result = handle_etl_trigger(sfn_client=client)

        assert result["status"] == "triggered"
        assert result["executionId"] == "arn:aws:states:us-east-1:123456789012:execution:etl-pipeline:exec-123"
        client.start_execution.assert_called_once_with(
            stateMachineArn="arn:aws:states:us-east-1:123456789012:stateMachine:etl-pipeline",
            input="{}",
        )

    @patch.dict(os.environ, {"STATE_MACHINE_ARN": ""})
    def test_missing_arn_returns_error(self):
        client = MagicMock()

        result = handle_etl_trigger(sfn_client=client)

        assert result["status"] == "error"
        assert "not configured" in result["message"]
        client.start_execution.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    def test_unset_env_var_returns_error(self):
        client = MagicMock()

        result = handle_etl_trigger(sfn_client=client)

        assert result["status"] == "error"
        client.start_execution.assert_not_called()
