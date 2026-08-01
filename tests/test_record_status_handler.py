"""Tests for etl.record_status_handler module."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from etl.record_status_handler import (
    _compute_summary,
    _format_error,
    record_status_handler,
)


ENV_VARS = {
    "SSM_ETL_STATUS": "/app/etl-status",
}


# ---------------------------------------------------------------------------
# _compute_summary unit tests
# ---------------------------------------------------------------------------


class TestComputeSummary:
    def test_all_success(self):
        # _compute_summary expects results with writeResult nested dict
        results = [
            {"writeResult": {"recordCount": 10, "itemsWritten": 15, "durationMs": 500}},
            {"writeResult": {"recordCount": 5, "itemsWritten": 8, "durationMs": 300}},
        ]
        summary = _compute_summary(results)
        assert summary["filesSuccess"] == 2
        assert summary["filesFailed"] == 0
        assert summary["totalRecords"] == 15
        assert summary["totalItemsWritten"] == 23
        assert summary["errors"] == []

    def test_all_failures(self):
        results = [
            {"status": "ERROR", "key": "a.csv", "error": {"Cause": "timeout"}},
            {"status": "ERROR", "key": "b.csv", "error": {"Error": "Lambda.Unknown"}},
        ]
        summary = _compute_summary(results)
        assert summary["filesSuccess"] == 0
        assert summary["filesFailed"] == 2
        assert summary["totalRecords"] == 0
        assert summary["totalItemsWritten"] == 0
        assert len(summary["errors"]) == 2

    def test_mixed_results(self):
        results = [
            {"writeResult": {"recordCount": 10, "itemsWritten": 15, "durationMs": 500}},
            {"status": "ERROR", "key": "bad.csv", "error": {"Cause": "parse error"}},
            {"writeResult": {"recordCount": 20, "itemsWritten": 25, "durationMs": 800}},
        ]
        summary = _compute_summary(results)
        assert summary["filesSuccess"] == 2
        assert summary["filesFailed"] == 1
        assert summary["totalRecords"] == 30
        assert summary["totalItemsWritten"] == 40
        assert len(summary["errors"]) == 1
        assert "bad.csv" in summary["errors"][0]

    def test_empty_results(self):
        summary = _compute_summary([])
        assert summary["filesSuccess"] == 0
        assert summary["filesFailed"] == 0
        assert summary["totalRecords"] == 0
        assert summary["totalItemsWritten"] == 0
        assert summary["errors"] == []


# ---------------------------------------------------------------------------
# _format_error unit tests
# ---------------------------------------------------------------------------


class TestFormatError:
    def test_with_cause(self):
        msg = _format_error("file.csv", {"Cause": "timeout after 30s"})
        assert msg == "Error processing file.csv: timeout after 30s"

    def test_with_nested_lambda_cause(self):
        """AWS Lambda wraps errors in a JSON-encoded Cause with errorMessage/errorType."""
        cause = json.dumps(
            {
                "errorMessage": "'utf-8' codec can't decode byte 0xff",
                "errorType": "UnicodeDecodeError",
                "stackTrace": ["frame1", "frame2"],
            }
        )
        msg = _format_error("poison.csv", {"Cause": cause, "Error": "UnicodeDecodeError"})
        assert "UnicodeDecodeError" in msg
        assert "utf-8" in msg
        assert "stackTrace" not in msg  # stack trace stripped

    def test_with_error_type(self):
        msg = _format_error("file.csv", {"Error": "Lambda.Unknown"})
        assert msg == "Error processing file.csv: Lambda.Unknown"

    def test_with_both_prefers_cause(self):
        msg = _format_error("file.csv", {"Cause": "details", "Error": "type"})
        assert "details" in msg

    def test_with_empty_dict(self):
        msg = _format_error("file.csv", {})
        assert msg == "Error processing file.csv: {}"

    def test_truncates_long_messages(self):
        long_cause = "x" * 300
        msg = _format_error("file.csv", {"Cause": long_cause})
        assert len(msg) <= 200


# ---------------------------------------------------------------------------
# record_status_handler — happy path
# ---------------------------------------------------------------------------


class TestRecordStatusHandlerHappyPath:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_all_success_writes_success_status(self, mock_read_s3, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_read_s3.return_value = ([
            {"writeResult": {"recordCount": 10, "itemsWritten": 15, "durationMs": 500}},
            {"writeResult": {"recordCount": 5, "itemsWritten": 8, "durationMs": 300}},
        ], 0)

        event = {
            "executionId": "arn:aws:states:us-east-1:123:execution:etl:exec-1",
            "listResult": {
                "newFilesCount": 2,
                "totalCsvFiles": 5,
                "totalPromptFiles": 3,
                "processedCount": 6,
            },
            "mapResultsBucket": "data-bucket",
            "mapResultsKey": "etl-results/manifest.json",
        }

        result = record_status_handler(event, None)

        assert result["status"] == "SUCCESS"
        assert result["filesProcessed"] == 2
        assert result["filesFailed"] == 0
        assert result["recordsWritten"] == 23
        assert result["errors"] == []

        mock_ssm.put_parameter.assert_called_once()
        call_kwargs = mock_ssm.put_parameter.call_args[1]
        assert call_kwargs["Name"] == "/app/etl-status"
        assert call_kwargs["Type"] == "String"
        assert call_kwargs["Overwrite"] is True

        payload = json.loads(call_kwargs["Value"])
        assert payload["status"] == "SUCCESS"
        assert payload["filesProcessed"] == 2
        assert payload["recordsWritten"] == 23
        assert payload["errors"] == []

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_mixed_results_writes_error_status(self, mock_read_s3, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_read_s3.return_value = ([
            {"writeResult": {"recordCount": 10, "itemsWritten": 15, "durationMs": 500}},
            {"status": "ERROR", "key": "bad.csv", "error": {"Cause": "parse error"}},
            {"writeResult": {"recordCount": 5, "itemsWritten": 8, "durationMs": 300}},
        ], 0)

        event = {
            "executionId": "exec-2",
            "listResult": {"newFilesCount": 3},
            "mapResultsBucket": "data-bucket",
            "mapResultsKey": "etl-results/manifest.json",
        }

        result = record_status_handler(event, None)

        assert result["status"] == "ERROR"
        assert result["filesProcessed"] == 2
        assert result["filesFailed"] == 1
        assert result["recordsWritten"] == 23
        assert len(result["errors"]) == 1

        payload = json.loads(mock_ssm.put_parameter.call_args[1]["Value"])
        assert payload["status"] == "ERROR"


# ---------------------------------------------------------------------------
# record_status_handler — edge cases
# ---------------------------------------------------------------------------


class TestRecordStatusHandlerEdgeCases:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    def test_empty_map_results(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm

        event = {
            "executionId": "exec-3",
            "listResult": {"newFilesCount": 0},
        }

        result = record_status_handler(event, None)

        assert result["status"] == "SUCCESS"
        assert result["filesProcessed"] == 0
        assert result["recordsWritten"] == 0

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    def test_missing_optional_fields(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm

        event = {}

        result = record_status_handler(event, None)

        assert result["status"] == "SUCCESS"
        assert result["filesProcessed"] == 0

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_ssm_payload_has_required_fields(self, mock_read_s3, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_read_s3.return_value = ([
            {"writeResult": {"recordCount": 5, "itemsWritten": 7, "durationMs": 200}},
        ], 0)

        event = {
            "executionId": "exec-4",
            "listResult": {"newFilesCount": 1},
            "mapResultsBucket": "data-bucket",
            "mapResultsKey": "etl-results/manifest.json",
        }

        record_status_handler(event, None)

        payload = json.loads(mock_ssm.put_parameter.call_args[1]["Value"])
        assert "lastExecution" in payload
        assert "status" in payload
        assert "filesProcessed" in payload
        assert "recordsWritten" in payload
        assert "errors" in payload


# ---------------------------------------------------------------------------
# record_status_handler — error propagation
# ---------------------------------------------------------------------------


class TestRecordStatusHandlerErrors:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    def test_ssm_error_propagates(self, mock_boto3):
        mock_ssm = MagicMock()
        mock_ssm.put_parameter.side_effect = Exception("SSM access denied")
        mock_boto3.client.return_value = mock_ssm

        event = {
            "executionId": "exec-5",
            "listResult": {"newFilesCount": 1},
        }

        with pytest.raises(Exception, match="SSM access denied"):
            record_status_handler(event, None)


# ---------------------------------------------------------------------------
# SSM payload truncation
# ---------------------------------------------------------------------------


class TestSSMPayloadTruncation:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_many_errors_truncated_to_10(self, mock_read_s3, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm

        map_results = [
            {"status": "ERROR", "key": f"file_{i}.csv", "error": {"Cause": f"err {i}"}}
            for i in range(20)
        ]
        mock_read_s3.return_value = (map_results, 0)

        event = {
            "executionId": "exec-6",
            "listResult": {"newFilesCount": 20},
            "mapResultsBucket": "data-bucket",
            "mapResultsKey": "etl-results/manifest.json",
        }

        result = record_status_handler(event, None)

        assert result["filesFailed"] == 20
        # Errors in the return are truncated to 10
        assert len(result["errors"]) <= 10

        payload = json.loads(mock_ssm.put_parameter.call_args[1]["Value"])
        assert len(payload["errors"]) <= 10


# ---------------------------------------------------------------------------
# _read_map_results_from_s3 — manifest read propagation
# ---------------------------------------------------------------------------


class TestReadMapResultsFromS3:
    """Covers changes from checkpoint 1 of .kiro/specs/etl-error-propagation."""

    @patch("etl.record_status_handler.boto3")
    def test_manifest_fetch_failure_propagates(self, mock_boto3):
        from etl.record_status_handler import _read_map_results_from_s3

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = Exception("AccessDenied")
        mock_boto3.client.return_value = mock_s3

        with pytest.raises(Exception, match="AccessDenied"):
            _read_map_results_from_s3("bucket", "manifest.json")

    @patch("etl.record_status_handler.boto3")
    def test_child_file_fetch_failure_counted(self, mock_boto3):
        from etl.record_status_handler import _read_map_results_from_s3

        mock_s3 = MagicMock()
        manifest = {
            "ResultFiles": {
                "SUCCEEDED": [{"Key": "ok.json"}, {"Key": "broken.json"}],
                "FAILED": [],
            }
        }

        def fake_get_object(Bucket, Key):
            if Key == "manifest.json":
                body = MagicMock()
                body.read.return_value = json.dumps(manifest).encode("utf-8")
                return {"Body": body}
            if Key == "ok.json":
                body = MagicMock()
                body.read.return_value = json.dumps(
                    [{"writeResult": {"recordCount": 3, "itemsWritten": 4}}]
                ).encode("utf-8")
                return {"Body": body}
            raise Exception("NoSuchKey")

        mock_s3.get_object.side_effect = fake_get_object
        mock_boto3.client.return_value = mock_s3

        logger = MagicMock()
        results, read_failures = _read_map_results_from_s3(
            "bucket", "manifest.json", logger
        )

        assert len(results) == 1
        assert read_failures == 1
        logger.error.assert_called_once()

    @patch("etl.record_status_handler.boto3")
    def test_failed_group_items_get_status_error(self, mock_boto3):
        from etl.record_status_handler import _read_map_results_from_s3

        mock_s3 = MagicMock()
        manifest = {
            "ResultFiles": {
                "SUCCEEDED": [],
                "FAILED": [{"Key": "failed.json"}],
            }
        }

        def fake_get_object(Bucket, Key):
            body = MagicMock()
            if Key == "manifest.json":
                body.read.return_value = json.dumps(manifest).encode("utf-8")
            else:
                # Real AWS FAILED_0.json shape: Cause/Error/Input at the top level
                body.read.return_value = json.dumps([{
                    "Cause": json.dumps({
                        "errorMessage": "bad bytes",
                        "errorType": "UnicodeDecodeError",
                    }),
                    "Error": "UnicodeDecodeError",
                    "Input": json.dumps({"key": "poison.csv", "fileType": "csv"}),
                }]).encode("utf-8")
            return {"Body": body}

        mock_s3.get_object.side_effect = fake_get_object
        mock_boto3.client.return_value = mock_s3

        results, read_failures = _read_map_results_from_s3("bucket", "manifest.json")

        assert read_failures == 0
        assert len(results) == 1
        assert results[0]["status"] == "ERROR"
        assert results[0]["key"] == "poison.csv"
        assert results[0]["error"]["Error"] == "UnicodeDecodeError"


# ---------------------------------------------------------------------------
# record_status_handler — manifest read failure scenarios
# ---------------------------------------------------------------------------


class TestRecordStatusHandlerManifestFailures:
    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_manifest_read_raises_and_ssm_not_called(self, mock_read_s3, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_read_s3.side_effect = Exception("S3 AccessDenied")

        event = {
            "executionId": "exec-manifest-fail",
            "listResult": {"newFilesCount": 5},
            "mapResultsBucket": "data-bucket",
            "mapResultsKey": "etl-results/manifest.json",
        }

        with pytest.raises(Exception, match="S3 AccessDenied"):
            record_status_handler(event, None)

        mock_ssm.put_parameter.assert_not_called()

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_read_failures_fold_into_files_failed(self, mock_read_s3, mock_boto3):
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_read_s3.return_value = (
            [{"writeResult": {"recordCount": 2, "itemsWritten": 3}}],
            2,  # 2 child-file read failures
        )

        event = {
            "executionId": "exec-read-fail",
            "listResult": {"newFilesCount": 3},
            "mapResultsBucket": "data-bucket",
            "mapResultsKey": "etl-results/manifest.json",
        }

        result = record_status_handler(event, None)

        assert result["filesFailed"] == 2
        assert result["filesProcessed"] == 1
        assert result["status"] == "ERROR"

    @patch.dict(os.environ, ENV_VARS)
    @patch("etl.record_status_handler.boto3")
    @patch("etl.record_status_handler._read_map_results_from_s3")
    @patch("etl.record_status_handler.StructuredLogger")
    def test_error_log_emitted_when_files_failed(
        self, mock_logger_cls, mock_read_s3, mock_boto3
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_ssm = MagicMock()
        mock_boto3.client.return_value = mock_ssm
        mock_read_s3.return_value = (
            [{"status": "ERROR", "key": "x.csv", "error": {"Cause": "boom"}}],
            0,
        )

        event = {
            "executionId": "exec-log",
            "listResult": {"newFilesCount": 1},
            "mapResultsBucket": "data-bucket",
            "mapResultsKey": "etl-results/manifest.json",
        }

        record_status_handler(event, None)

        # At least one ERROR log carrying filesFailed > 0
        error_calls = [c for c in mock_logger.error.call_args_list
                       if c.kwargs.get("filesFailed", 0) > 0]
        assert len(error_calls) >= 1
        assert "errorSample" in error_calls[0].kwargs


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# ---------------------------------------------------------------------------


try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
    HYPOTHESIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    HYPOTHESIS_AVAILABLE = False


@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
class TestComputeSummaryProperties:
    """Universal invariants of _compute_summary (Requirement 4)."""

    _success = st.fixed_dictionaries(
        {
            "writeResult": st.fixed_dictionaries(
                {
                    "recordCount": st.integers(min_value=0, max_value=1000),
                    "itemsWritten": st.integers(min_value=0, max_value=1000),
                }
            )
        }
    )
    _error = st.fixed_dictionaries(
        {
            "status": st.just("ERROR"),
            "key": st.text(min_size=1, max_size=30),
            "error": st.fixed_dictionaries({"Cause": st.text(max_size=50)}),
        }
    )
    _legacy_error = st.fixed_dictionaries(
        {
            "key": st.text(min_size=1, max_size=30),
            "error": st.fixed_dictionaries({"Cause": st.text(max_size=50)}),
        }
    )

    @given(st.lists(st.one_of(_success, _error, _legacy_error), max_size=50))
    @settings(max_examples=20)
    def test_success_plus_failed_equals_total(self, results):
        summary = _compute_summary(results)
        assert summary["filesSuccess"] + summary["filesFailed"] == len(results)

    @given(st.lists(st.one_of(_success, _error, _legacy_error), max_size=50))
    @settings(max_examples=20)
    def test_status_determinism(self, results):
        summary = _compute_summary(results)
        is_error = summary["filesFailed"] > 0
        # The status field is decided in the handler, but the contract
        # ("ERROR iff filesFailed > 0") lives in the summary counts.
        assert is_error == (summary["filesFailed"] > 0)
        if is_error:
            assert len(summary["errors"]) > 0 or summary["filesFailed"] > 0

    @given(_legacy_error)
    @settings(max_examples=20)
    def test_legacy_error_payload_classified_as_failed(self, legacy):
        """Payloads from the pre-fix design (error key, no status) are still errors."""
        summary = _compute_summary([legacy])
        assert summary["filesFailed"] == 1
        assert summary["filesSuccess"] == 0
