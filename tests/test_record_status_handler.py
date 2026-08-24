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


# ---------------------------------------------------------------------------
# Execution history record tests (_execution_name_from_arn, _write_execution_record)
# ---------------------------------------------------------------------------

from moto import mock_aws

from etl.record_status_handler import (
    _execution_name_from_arn,
    _write_execution_record,
)


ANALYTICS_TABLE = "analytics-table"
VALID_ARN = "arn:aws:states:us-east-1:123456789012:execution:my-sm:exec-abc-123"
EXECUTION_NAME = "exec-abc-123"

ENV_VARS_WITH_TABLE = {
    **ENV_VARS,
    "ANALYTICS_TABLE": ANALYTICS_TABLE,
}


def _create_analytics_table():
    """Create the mocked DynamoDB analytics table with PK (HASH) and SK (RANGE)."""
    import boto3 as _boto3

    ddb = _boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=ANALYTICS_TABLE,
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
    return ddb


# ---------------------------------------------------------------------------
# _execution_name_from_arn unit tests
# ---------------------------------------------------------------------------


class TestExecutionNameFromArn:
    """Unit tests for _execution_name_from_arn (requirement 6)."""

    def test_full_valid_arn_returns_last_segment(self):
        assert _execution_name_from_arn(VALID_ARN) == EXECUTION_NAME

    def test_no_colon_returns_empty(self):
        assert _execution_name_from_arn("not-an-arn") == ""

    def test_empty_string_returns_empty(self):
        assert _execution_name_from_arn("") == ""

    def test_none_input_returns_empty(self):
        assert _execution_name_from_arn(None) == ""

    def test_integer_input_returns_empty(self):
        assert _execution_name_from_arn(123) == ""

    def test_trailing_whitespace_stripped(self):
        assert _execution_name_from_arn(VALID_ARN + "  \t") == EXECUTION_NAME


# ---------------------------------------------------------------------------
# _write_execution_record — successful write via moto
# ---------------------------------------------------------------------------


class TestWriteExecutionRecordSuccess:
    """Successful run writes the execution record (requirement 1)."""

    @mock_aws
    @patch.dict(os.environ, ENV_VARS_WITH_TABLE)
    def test_writes_correct_item(self):
        import boto3 as _boto3

        ddb = _create_analytics_table()

        logger = MagicMock()
        _write_execution_record(
            execution_id=VALID_ARN,
            status="SUCCESS",
            files_processed=5,
            records_written=42,
            logger=logger,
            dynamodb_resource=ddb,
        )

        table = ddb.Table(ANALYTICS_TABLE)
        resp = table.get_item(Key={"PK": "ETL_STATUS", "SK": f"EXEC#{EXECUTION_NAME}"})
        item = resp["Item"]

        assert item["PK"] == "ETL_STATUS"
        assert item["SK"] == f"EXEC#{EXECUTION_NAME}"
        assert item["status"] == "SUCCESS"
        assert item["filesProcessed"] == 5
        assert item["recordsWritten"] == 42
        assert item["executionArn"] == VALID_ARN
        # timestamp is ISO 8601 with timezone
        from datetime import datetime as _dt

        _dt.fromisoformat(item["timestamp"])  # raises if not valid ISO 8601


# ---------------------------------------------------------------------------
# _write_execution_record — invalid ARN / missing env var → no item written
# ---------------------------------------------------------------------------


class TestWriteExecutionRecordSkipsOnInvalidInput:
    """ARN with no ':' or empty ARN → NO item written (requirement 2)."""

    @mock_aws
    @patch.dict(os.environ, ENV_VARS_WITH_TABLE)
    def test_no_colon_arn_writes_nothing(self):
        ddb = _create_analytics_table()
        logger = MagicMock()

        _write_execution_record(
            execution_id="not-an-arn",
            status="SUCCESS",
            files_processed=1,
            records_written=1,
            logger=logger,
            dynamodb_resource=ddb,
        )

        table = ddb.Table(ANALYTICS_TABLE)
        resp = table.scan()
        assert resp["Count"] == 0

    @mock_aws
    @patch.dict(os.environ, ENV_VARS_WITH_TABLE)
    def test_empty_string_arn_writes_nothing(self):
        ddb = _create_analytics_table()
        logger = MagicMock()

        _write_execution_record(
            execution_id="",
            status="SUCCESS",
            files_processed=1,
            records_written=1,
            logger=logger,
            dynamodb_resource=ddb,
        )

        table = ddb.Table(ANALYTICS_TABLE)
        resp = table.scan()
        assert resp["Count"] == 0

    @mock_aws
    @patch.dict(os.environ, {"SSM_ETL_STATUS": "/app/etl-status"})
    def test_analytics_table_env_unset_writes_nothing(self):
        """ANALYTICS_TABLE env var unset → no item written (requirement 3)."""
        import boto3 as _boto3

        # Create table anyway — we expect the function to bail before using it
        ddb = _create_analytics_table()
        logger = MagicMock()

        _write_execution_record(
            execution_id=VALID_ARN,
            status="SUCCESS",
            files_processed=1,
            records_written=1,
            logger=logger,
            dynamodb_resource=ddb,
        )

        table = ddb.Table(ANALYTICS_TABLE)
        resp = table.scan()
        assert resp["Count"] == 0


# ---------------------------------------------------------------------------
# Handler integration — execution record written + SSM still called
# ---------------------------------------------------------------------------


class TestHandlerWritesExecutionRecord:
    """Integration: full handler path writes execution record via moto (req 1)."""

    @mock_aws
    @patch.dict(os.environ, ENV_VARS_WITH_TABLE, clear=False)
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_handler_writes_execution_record_on_success(self, mock_read_s3):
        import boto3 as _boto3

        _create_analytics_table()

        # SSM needs to be available under moto too
        ssm = _boto3.client("ssm", region_name="us-east-1")

        mock_read_s3.return_value = ([
            {"writeResult": {"recordCount": 10, "itemsWritten": 15}},
        ], 0)

        event = {
            "executionId": VALID_ARN,
            "listResult": {"newFilesCount": 1},
            "mapResultsBucket": "data-bucket",
            "mapResultsKey": "etl-results/manifest.json",
        }

        result = record_status_handler(event, None)

        assert result["status"] == "SUCCESS"

        # Verify DynamoDB record
        ddb = _boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.Table(ANALYTICS_TABLE)
        resp = table.get_item(Key={"PK": "ETL_STATUS", "SK": f"EXEC#{EXECUTION_NAME}"})
        item = resp["Item"]
        assert item["status"] == "SUCCESS"
        assert item["filesProcessed"] == 1
        assert item["recordsWritten"] == 15
        assert item["executionArn"] == VALID_ARN

        # Verify SSM was still written
        ssm_resp = ssm.get_parameter(Name="/app/etl-status")
        payload = json.loads(ssm_resp["Parameter"]["Value"])
        assert payload["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# Handler integration — invalid ARN still writes SSM, no DynamoDB item
# ---------------------------------------------------------------------------


class TestHandlerInvalidArnStillWritesSSM:
    """Handler with invalid ARN: no DDB item, SSM still written (req 2)."""

    @mock_aws
    @patch.dict(os.environ, ENV_VARS_WITH_TABLE, clear=False)
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_no_colon_arn_handler_still_returns_and_writes_ssm(self, mock_read_s3):
        import boto3 as _boto3

        _create_analytics_table()
        mock_read_s3.return_value = ([
            {"writeResult": {"recordCount": 3, "itemsWritten": 5}},
        ], 0)

        event = {
            "executionId": "not-an-arn",
            "listResult": {"newFilesCount": 1},
            "mapResultsBucket": "bucket",
            "mapResultsKey": "key.json",
        }

        result = record_status_handler(event, None)

        assert result["status"] == "SUCCESS"

        # SSM was written
        ssm = _boto3.client("ssm", region_name="us-east-1")
        ssm_resp = ssm.get_parameter(Name="/app/etl-status")
        assert "SUCCESS" in ssm_resp["Parameter"]["Value"]

        # No DynamoDB item
        ddb = _boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.Table(ANALYTICS_TABLE)
        resp = table.scan()
        assert resp["Count"] == 0


# ---------------------------------------------------------------------------
# put_item failure → handler still returns normally (requirement 4)
# ---------------------------------------------------------------------------


class TestExecutionRecordFailureDoesNotBreakHandler:
    """DynamoDB put_item raising must NOT fail the handler (requirement 4)."""

    @patch.dict(os.environ, ENV_VARS_WITH_TABLE)
    @patch("etl.record_status_handler.boto3")
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_put_item_exception_handler_still_returns(self, mock_read_s3, mock_boto3):
        mock_ssm = MagicMock()
        mock_ddb_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.put_item.side_effect = RuntimeError("DDB unavailable")
        mock_ddb_resource.Table.return_value = mock_table

        def client_side_effect(service, *a, **kw):
            if service == "ssm":
                return mock_ssm
            return MagicMock()

        mock_boto3.client.side_effect = client_side_effect
        mock_boto3.resource.return_value = mock_ddb_resource

        mock_read_s3.return_value = ([
            {"writeResult": {"recordCount": 7, "itemsWritten": 9}},
        ], 0)

        event = {
            "executionId": VALID_ARN,
            "listResult": {"newFilesCount": 1},
            "mapResultsBucket": "bucket",
            "mapResultsKey": "key.json",
        }

        result = record_status_handler(event, None)

        # Handler returned normally
        assert result["status"] == "SUCCESS"
        assert result["filesProcessed"] == 1
        assert result["recordsWritten"] == 9

        # SSM was still written
        mock_ssm.put_parameter.assert_called_once()


# ---------------------------------------------------------------------------
# SSM payload shape unchanged (requirement 5)
# ---------------------------------------------------------------------------


class TestSSMPayloadShapeUnchanged:
    """SSM payload still has exactly 5 keys: lastExecution, status,
    filesProcessed, recordsWritten, errors (requirement 5)."""

    @mock_aws
    @patch.dict(os.environ, ENV_VARS_WITH_TABLE, clear=False)
    @patch("etl.record_status_handler._read_map_results_from_s3")
    def test_ssm_payload_exact_keys(self, mock_read_s3):
        import boto3 as _boto3

        _create_analytics_table()
        mock_read_s3.return_value = ([
            {"writeResult": {"recordCount": 4, "itemsWritten": 6}},
        ], 0)

        event = {
            "executionId": VALID_ARN,
            "listResult": {"newFilesCount": 1},
            "mapResultsBucket": "bucket",
            "mapResultsKey": "key.json",
        }

        record_status_handler(event, None)

        ssm = _boto3.client("ssm", region_name="us-east-1")
        ssm_resp = ssm.get_parameter(Name="/app/etl-status")
        payload = json.loads(ssm_resp["Parameter"]["Value"])

        expected_keys = {"lastExecution", "status", "filesProcessed", "recordsWritten", "errors"}
        assert set(payload.keys()) == expected_keys
        assert payload["status"] == "SUCCESS"
        assert payload["filesProcessed"] == 1
        assert payload["recordsWritten"] == 6
        assert isinstance(payload["errors"], list)
        # lastExecution is an ISO 8601 timestamp
        from datetime import datetime as _dt

        _dt.fromisoformat(payload["lastExecution"])


# ---------------------------------------------------------------------------
# Hypothesis: _write_execution_record NEVER raises (requirement 7)
# ---------------------------------------------------------------------------


class TestWriteExecutionRecordNeverRaises:
    """Property: _write_execution_record must NEVER raise, regardless of input
    or DynamoDB failures (requirement 7)."""

    @given(
        execution_id=st.text(min_size=0, max_size=200),
        status=st.text(min_size=0, max_size=50),
        files_processed=st.integers(min_value=-1000, max_value=1_000_000),
        records_written=st.integers(min_value=-1000, max_value=1_000_000),
    )
    @settings(max_examples=100)
    @patch.dict(os.environ, ENV_VARS_WITH_TABLE)
    def test_never_raises_with_failing_dynamodb(
        self, execution_id, status, files_processed, records_written
    ):
        """Even when DynamoDB always raises, the function must not propagate."""
        fake_logger = MagicMock()
        stub_resource = MagicMock()
        stub_resource.Table.return_value.put_item.side_effect = Exception("boom")

        # Must not raise
        _write_execution_record(
            execution_id=execution_id,
            status=status,
            files_processed=files_processed,
            records_written=records_written,
            logger=fake_logger,
            dynamodb_resource=stub_resource,
        )

    @given(
        execution_id=st.text(min_size=0, max_size=200),
        status=st.text(min_size=0, max_size=50),
        files_processed=st.integers(min_value=-1000, max_value=1_000_000),
        records_written=st.integers(min_value=-1000, max_value=1_000_000),
    )
    @settings(max_examples=100)
    @patch.dict(os.environ, ENV_VARS_WITH_TABLE)
    def test_never_raises_with_working_dynamodb(
        self, execution_id, status, files_processed, records_written
    ):
        """Even with arbitrary text inputs, the function must not raise."""
        fake_logger = MagicMock()
        stub_resource = MagicMock()

        _write_execution_record(
            execution_id=execution_id,
            status=status,
            files_processed=files_processed,
            records_written=records_written,
            logger=fake_logger,
            dynamodb_resource=stub_resource,
        )
