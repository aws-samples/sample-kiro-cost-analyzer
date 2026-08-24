"""Tests for backend.handlers.etl_executions_handler module."""

import os
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from backend.handlers.etl_executions_handler import (
    _elapsed_seconds,
    _parse_days,
    handle_etl_executions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
_TABLE_NAME = "analytics-table"


def _make_execution(name: str, start: datetime, stop=None, status="SUCCEEDED"):
    """Build a Step Functions execution dict matching boto3 paginator shape."""
    execution = {
        "name": name,
        "executionArn": f"arn:aws:states:us-east-1:123456789012:execution:etl:{name}",
        "stateMachineArn": "arn:aws:states:us-east-1:123456789012:stateMachine:etl-pipeline",
        "startDate": start,
        "status": status,
    }
    if stop is not None:
        execution["stopDate"] = stop
    return execution


class FakePaginator:
    """Stub paginator that yields pre-configured pages and tracks calls."""

    def __init__(self, pages: list[list[dict]]):
        self._pages = pages
        self.paginate_calls = []

    def paginate(self, **kwargs):
        self.paginate_calls.append(kwargs)
        for page in self._pages:
            yield {"executions": page}


class FakeSFNClient:
    """Stub SFN client exposing get_paginator with a FakePaginator."""

    def __init__(self, pages: list[list[dict]]):
        self._paginator = FakePaginator(pages)

    def get_paginator(self, operation_name):
        assert operation_name == "list_executions"
        return self._paginator

    @property
    def paginator(self):
        return self._paginator


def _create_analytics_table():
    """Create the DynamoDB analytics table in the moto-mocked environment."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName=_TABLE_NAME,
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
    return dynamodb


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Two executions, one enriched from DynamoDB."""

    @mock_aws
    @patch.dict(os.environ, {
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:etl-pipeline",
        "ANALYTICS_TABLE": _TABLE_NAME,
    })
    def test_two_executions_one_enriched(self):
        dynamodb = _create_analytics_table()
        table = dynamodb.Table(_TABLE_NAME)
        table.put_item(Item={
            "PK": "ETL_STATUS",
            "SK": "EXEC#exec-001",
            "filesProcessed": 5,
            "recordsWritten": 1200,
        })

        start1 = _NOW - timedelta(hours=2)
        stop1 = _NOW - timedelta(hours=1, minutes=50)
        start2 = _NOW - timedelta(hours=1)
        stop2 = _NOW - timedelta(minutes=30)

        executions = [
            _make_execution("exec-002", start2, stop2, "SUCCEEDED"),
            _make_execution("exec-001", start1, stop1, "SUCCEEDED"),
        ]

        client = FakeSFNClient([[executions[0], executions[1]]])

        result = handle_etl_executions(
            {"days": "5"},
            sfn_client=client,
            dynamodb_resource=dynamodb,
        )

        assert result["days"] == 5
        assert len(result["executions"]) == 2

        # First execution (exec-002) has no DynamoDB record
        ex2 = result["executions"][0]
        assert ex2["executionName"] == "exec-002"
        assert ex2["startDate"] == start2.isoformat()
        assert ex2["stopDate"] == stop2.isoformat()
        assert ex2["elapsedSeconds"] == int((stop2 - start2).total_seconds())
        assert ex2["status"] == "SUCCEEDED"
        assert ex2["filesProcessed"] is None
        assert ex2["recordsWritten"] is None

        # Second execution (exec-001) enriched from DynamoDB
        ex1 = result["executions"][1]
        assert ex1["executionName"] == "exec-001"
        assert ex1["startDate"] == start1.isoformat()
        assert ex1["stopDate"] == stop1.isoformat()
        assert ex1["elapsedSeconds"] == int((stop1 - start1).total_seconds())
        assert ex1["status"] == "SUCCEEDED"
        assert ex1["filesProcessed"] == 5
        assert ex1["recordsWritten"] == 1200


# ---------------------------------------------------------------------------
# Running execution
# ---------------------------------------------------------------------------


class TestRunningExecution:
    """Running execution: no stopDate, elapsedSeconds is None."""

    @mock_aws
    @patch.dict(os.environ, {
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:etl-pipeline",
        "ANALYTICS_TABLE": _TABLE_NAME,
    })
    def test_running_execution_fields(self):
        _create_analytics_table()

        start = _NOW - timedelta(minutes=5)
        execution = _make_execution("exec-running", start, stop=None, status="RUNNING")

        client = FakeSFNClient([[execution]])
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        result = handle_etl_executions(
            {"days": "5"},
            sfn_client=client,
            dynamodb_resource=dynamodb,
        )

        assert len(result["executions"]) == 1
        ex = result["executions"][0]
        assert ex["stopDate"] is None
        assert ex["elapsedSeconds"] is None
        assert ex["status"] == "RUNNING"


# ---------------------------------------------------------------------------
# No matching EXEC# record
# ---------------------------------------------------------------------------


class TestNoMatchingExecRecord:
    """Execution with no EXEC# DynamoDB record -> counters are None (NOT 0)."""

    @mock_aws
    @patch.dict(os.environ, {
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:etl-pipeline",
        "ANALYTICS_TABLE": _TABLE_NAME,
    })
    def test_no_record_counters_are_none(self):
        _create_analytics_table()

        start = _NOW - timedelta(hours=1)
        stop = _NOW - timedelta(minutes=30)
        execution = _make_execution("exec-no-record", start, stop, "SUCCEEDED")

        client = FakeSFNClient([[execution]])
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        result = handle_etl_executions(
            {"days": "5"},
            sfn_client=client,
            dynamodb_resource=dynamodb,
        )

        ex = result["executions"][0]
        assert ex["filesProcessed"] is None, "filesProcessed must be None, not 0"
        assert ex["recordsWritten"] is None, "recordsWritten must be None, not 0"


# ---------------------------------------------------------------------------
# Window filtering and paging cutoff
# ---------------------------------------------------------------------------


class TestWindowFiltering:
    """Executions older than the cutoff are excluded; paging stops."""

    @mock_aws
    @patch.dict(os.environ, {
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:etl-pipeline",
        "ANALYTICS_TABLE": _TABLE_NAME,
    })
    def test_cutoff_excludes_old_and_stops_paging(self):
        _create_analytics_table()

        recent_start = _NOW - timedelta(hours=1)
        recent_stop = _NOW - timedelta(minutes=30)
        old_start = _NOW - timedelta(days=10)
        old_stop = _NOW - timedelta(days=9)

        # Page 1: one recent, one old (triggers cutoff)
        page1 = [
            _make_execution("exec-recent", recent_start, recent_stop),
            _make_execution("exec-old", old_start, old_stop),
        ]
        # Page 2: should never be reached
        page2 = [
            _make_execution("exec-page2", _NOW - timedelta(days=20), _NOW - timedelta(days=19)),
        ]

        client = FakeSFNClient([page1, page2])
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        result = handle_etl_executions(
            {"days": "5"},
            sfn_client=client,
            dynamodb_resource=dynamodb,
        )

        # Only the recent one should be in the result
        assert len(result["executions"]) == 1
        assert result["executions"][0]["executionName"] == "exec-recent"

        # The paginator was only called once (page 2 never requested)
        assert len(client.paginator.paginate_calls) == 1


# ---------------------------------------------------------------------------
# STATE_MACHINE_ARN unset/empty
# ---------------------------------------------------------------------------


class TestStateMachineArnUnset:
    """Missing or empty STATE_MACHINE_ARN returns empty without calling SFN."""

    @patch.dict(os.environ, {"STATE_MACHINE_ARN": "", "ANALYTICS_TABLE": ""})
    def test_empty_arn_returns_empty(self):
        client = MagicMock()

        result = handle_etl_executions({"days": "3"}, sfn_client=client)

        assert result == {"days": 3, "executions": []}
        client.get_paginator.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    def test_unset_arn_returns_empty(self):
        client = MagicMock()

        result = handle_etl_executions({}, sfn_client=client)

        assert result == {"days": 5, "executions": []}
        client.get_paginator.assert_not_called()


# ---------------------------------------------------------------------------
# Days parsing and clamping
# ---------------------------------------------------------------------------


class TestDaysParsing:
    """_parse_days: absent -> 5, '10' -> 10, '0' -> 1, '999' -> 30, 'abc' -> 5, None -> 5."""

    def test_absent_returns_default(self):
        assert _parse_days({}) == 5

    def test_none_params_returns_default(self):
        assert _parse_days(None) == 5

    def test_valid_string_10(self):
        assert _parse_days({"days": "10"}) == 10

    def test_clamp_zero_to_min(self):
        assert _parse_days({"days": "0"}) == 1

    def test_clamp_999_to_max(self):
        assert _parse_days({"days": "999"}) == 30

    def test_non_numeric_returns_default(self):
        assert _parse_days({"days": "abc"}) == 5

    def test_none_value_returns_default(self):
        assert _parse_days({"days": None}) == 5


# ---------------------------------------------------------------------------
# ClientError propagation
# ---------------------------------------------------------------------------


class TestClientErrorPropagation:
    """botocore ClientError from list_executions MUST propagate."""

    @patch.dict(os.environ, {
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:etl-pipeline",
        "ANALYTICS_TABLE": "",
    })
    def test_client_error_not_swallowed(self):
        error_response = {
            "Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}
        }

        class ErrorPaginator:
            def paginate(self, **kwargs):
                raise ClientError(error_response, "ListExecutions")

        class ErrorClient:
            def get_paginator(self, op):
                return ErrorPaginator()

        with pytest.raises(ClientError, match="Not authorized"):
            handle_etl_executions({}, sfn_client=ErrorClient())


# ---------------------------------------------------------------------------
# English-only response assertion
# ---------------------------------------------------------------------------


class TestEnglishOnlyResponse:
    """All human-readable fields must be English; statuses are raw SFN slugs."""

    _NON_ASCII_WORD = re.compile(r"[^\x00-\x7F]")

    @mock_aws
    @patch.dict(os.environ, {
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:etl-pipeline",
        "ANALYTICS_TABLE": _TABLE_NAME,
    })
    def test_no_non_ascii_in_response(self):
        _create_analytics_table()

        start = _NOW - timedelta(hours=1)
        stop = _NOW - timedelta(minutes=30)
        execution = _make_execution("exec-en", start, stop, "SUCCEEDED")

        client = FakeSFNClient([[execution]])
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        result = handle_etl_executions(
            {"days": "5"},
            sfn_client=client,
            dynamodb_resource=dynamodb,
        )

        # Check all string fields in the response
        for ex in result["executions"]:
            for key, value in ex.items():
                if isinstance(value, str):
                    assert not self._NON_ASCII_WORD.search(value), (
                        f"Non-ASCII found in {key}: {value!r}"
                    )

        # Status values are raw uppercase SFN slugs
        valid_statuses = {"RUNNING", "SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED", "UNKNOWN"}
        for ex in result["executions"]:
            assert ex["status"] in valid_statuses


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------


class TestParseDaysProperty:
    """P1: _parse_days totality — any text input yields an int in 1..30."""

    @given(st.text(max_size=50))
    @settings(max_examples=100)
    def test_always_returns_int_in_range(self, raw):
        result = _parse_days({"days": raw})
        assert isinstance(result, int)
        assert 1 <= result <= 30


class TestElapsedSecondsProperty:
    """P3: _elapsed_seconds returns None when either bound is not a datetime, else non-negative."""

    _datetimes = st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 1, 1),
        timezones=st.just(timezone.utc),
    )
    _non_datetimes = st.one_of(st.none(), st.text(max_size=20), st.integers())

    @given(start=_datetimes, stop=_datetimes)
    @settings(max_examples=100)
    def test_two_datetimes_returns_non_negative_or_none(self, start, stop):
        result = _elapsed_seconds(start, stop)
        if stop >= start:
            assert result is not None
            assert result >= 0
        else:
            # Negative diff -> None
            assert result is None

    @given(start=_non_datetimes, stop=_datetimes)
    @settings(max_examples=100)
    def test_non_datetime_start_returns_none(self, start, stop):
        result = _elapsed_seconds(start, stop)
        assert result is None

    @given(start=_datetimes, stop=_non_datetimes)
    @settings(max_examples=100)
    def test_non_datetime_stop_returns_none(self, start, stop):
        result = _elapsed_seconds(start, stop)
        assert result is None
