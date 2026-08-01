"""Unit tests for custom_resources/mapping_migrator.py.

Covers the example-test cases the design's Testing Strategy assigns to
this file rather than to a Hypothesis property (`test_mapping_migrator.py`
row of the Unit Tests table): structured log content per migrated pair
and on the summary record (Requirement 11.7), per-item failure resilience
(Requirement 11.8), the already-migrated no-op, the partially-migrated
convergence case, and the response watchdog's early stop.

Properties 24 and 25 (`tests/test_git_mapping_properties.py`) already
quantify broadly over untruncated and partially-migrated inputs; this file
does not repeat that breadth. It exists for the concrete branches those
properties cannot express — a specific logged field, a specific failure
injected at one item, a specific truncated clock — per the design's note
that "unit tests stay deliberately thin."

Every call to `migrate()` below passes all three positional arguments
(`table`, `logger`, `remaining_ms`), matching the design's note that the
signature is `migrate(table, logger, remaining_ms)` with no default for
the third argument.
"""

from __future__ import annotations

import itertools
import json
from unittest.mock import MagicMock, patch

import boto3
from moto import mock_aws

from custom_resources import mapping_migrator as module
from custom_resources.mapping_migrator import RESPONSE_MARGIN_MS, migrate
from git_shared.git_providers import mapping_sort_key
from git_shared.git_repository import GitRepository


TABLE_NAME = "TestAnalyticsTable"


def _create_table(resource):
    """Create the mocked Analytics_Table with the standard PK/SK schema."""
    resource.create_table(
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


def _put_legacy_item(table, user_id, provider, git_username, created_at=None, created_by=None):
    """Write one Legacy_Mapping_Sort_Key item directly, bypassing
    `put_user_mapping` (which can no longer produce this key shape).
    """
    item = {
        "PK": f"USER#{user_id}",
        "SK": f"GITMAP#{provider}#{git_username}",
        "provider": provider,
        "gitUsername": git_username,
    }
    if created_at is not None:
        item["createdAt"] = created_at
    if created_by is not None:
        item["createdBy"] = created_by
    table.put_item(Item=item)
    return item


def _make_event(table_name=TABLE_NAME, request_type="Create", migration_version="1"):
    return {
        "RequestType": request_type,
        "ResponseURL": "https://cloudformation-custom-resource-response.example.com",
        "StackId": "arn:aws:cloudformation:us-east-1:123456789012:stack/test/guid",
        "RequestId": "unique-id-1234",
        "LogicalResourceId": "MappingMigration",
        "ResourceProperties": {
            "TableName": table_name,
            "MigrationVersion": migration_version,
        },
    }


def _make_context(remaining_ms_values=None):
    ctx = MagicMock()
    ctx.log_stream_name = "test-log-stream"
    if remaining_ms_values is not None:
        ctx.get_remaining_time_in_millis.side_effect = remaining_ms_values
    return ctx


class _FailingPutItemTable:
    """Wraps a real (moto-backed) Table and raises on `put_item` for one
    chosen item, matched by (PK, SK), while every other operation is
    forwarded unchanged to the wrapped table.

    Used to exercise the per-item failure resilience path (Requirement
    11.8) with a fault injected at exactly one item rather than moto's own
    fault-injection support, which cannot target a single item's key.
    """

    def __init__(self, table, fail_key):
        self._table = table
        self._fail_key = fail_key

    def put_item(self, **kwargs):
        item = kwargs.get("Item", {})
        if (item.get("PK"), item.get("SK")) == self._fail_key:
            raise RuntimeError("Simulated DynamoDB failure")
        return self._table.put_item(**kwargs)

    def delete_item(self, **kwargs):
        return self._table.delete_item(**kwargs)

    def scan(self, **kwargs):
        return self._table.scan(**kwargs)

    def get_item(self, **kwargs):
        return self._table.get_item(**kwargs)


class TestStructuredLogPerMigratedPair:
    """Requirement 11.7: one structured log record per migrated pair,
    naming the userId, the provider, the retained gitUsername, and the
    number of discarded mappings.
    """

    def test_logs_userid_provider_username_and_discarded_count(self):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            table = resource.Table(TABLE_NAME)

            _put_legacy_item(table, "user-1", "github", "alice", created_at="2024-01-01T00:00:00Z")
            _put_legacy_item(table, "user-1", "github", "zed", created_at="2023-01-01T00:00:00Z")

            logger = MagicMock()

            report = migrate(table, logger, lambda: 999_999)

            assert report["migrated"] == 1
            assert report["discarded"] == 1

            migrated_calls = [
                call for call in logger.info.call_args_list if call.args[0] == "Migrated mapping"
            ]
            assert len(migrated_calls) == 1
            _, kwargs = migrated_calls[0]
            assert kwargs["userId"] == "user-1"
            assert kwargs["provider"] == "github"
            assert kwargs["gitUsername"] == "alice"
            assert kwargs["discarded"] == 1


class TestSummaryRecord:
    """Requirement 11.7 (summary record): the run's summary log entry
    carries the full count breakdown plus the `truncated` flag and the
    `unconverted` count — the only signal that distinguishes a partial
    run from a complete one, since both report `SUCCESS`.
    """

    def test_summary_record_carries_counts_truncated_and_unconverted(self):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            table = resource.Table(TABLE_NAME)

            _put_legacy_item(table, "user-1", "github", "alice", created_at="2024-01-01T00:00:00Z")
            _put_legacy_item(table, "user-2", "gitlab", "bob", created_at="2024-01-01T00:00:00Z")

            logger = MagicMock()

            report = migrate(table, logger, lambda: 999_999)

            summary_calls = [
                call
                for call in logger.info.call_args_list
                if call.args[0] == "Mapping migration summary"
            ]
            assert len(summary_calls) == 1
            _, kwargs = summary_calls[0]
            assert kwargs["scanned"] == report["scanned"]
            assert kwargs["migrated"] == report["migrated"]
            assert kwargs["discarded"] == report["discarded"]
            assert kwargs["failed"] == report["failed"]
            assert kwargs["unconverted"] == report["unconverted"]
            assert kwargs["truncated"] == report["truncated"]

            assert report["truncated"] is False
            assert report["unconverted"] == 0
            assert report["migrated"] == 2


class TestPerItemFailureResilience:
    """Requirement 11.8: a failure migrating one pair is logged with its
    userId and provider, and the run continues over the remaining pairs
    rather than stopping.
    """

    def test_one_failing_pair_does_not_stop_the_run(self):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            table = resource.Table(TABLE_NAME)

            _put_legacy_item(table, "user-1", "github", "alice", created_at="2024-01-01T00:00:00Z")
            _put_legacy_item(table, "user-2", "gitlab", "bob", created_at="2024-01-01T00:00:00Z")
            _put_legacy_item(table, "user-3", "github", "carol", created_at="2024-01-01T00:00:00Z")

            failing_key = ("USER#user-2", mapping_sort_key("gitlab"))
            faulty_table = _FailingPutItemTable(table, fail_key=failing_key)

            logger = MagicMock()

            report = migrate(faulty_table, logger, lambda: 999_999)

            assert report["failed"] == 1
            assert report["migrated"] == 2
            assert report["unconverted"] == 1
            assert report["truncated"] is False

            error_calls = [
                call
                for call in logger.error.call_args_list
                if call.args[0] == "Failed to migrate mapping"
            ]
            assert len(error_calls) == 1
            _, kwargs = error_calls[0]
            assert kwargs["userId"] == "user-2"
            assert kwargs["provider"] == "gitlab"

            # The other two pairs migrated normally despite the failure.
            for user_id, provider in [("user-1", "github"), ("user-3", "github")]:
                response = table.get_item(
                    Key={"PK": f"USER#{user_id}", "SK": mapping_sort_key(provider)}
                )
                assert "Item" in response

            # The failing pair's legacy item survives untouched — put_item
            # raised before the delete loop ran, so nothing was removed
            # for it.
            legacy_response = table.get_item(Key={"PK": "USER#user-2", "SK": "GITMAP#gitlab#bob"})
            assert "Item" in legacy_response

            # And it stays retrievable through the read path that
            # tolerates both key shapes.
            repo = GitRepository(TABLE_NAME, dynamodb_resource=resource)
            remaining = repo.list_user_mappings("user-2")
            assert any(m["gitUsername"] == "bob" for m in remaining)


class TestAlreadyMigratedNoOp:
    """A table holding only current-shaped items (nothing legacy) is a
    no-op: `migrate()` finds nothing to group and returns the all-zero
    report without touching any item.
    """

    def test_no_legacy_items_produces_all_zero_report(self):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            table = resource.Table(TABLE_NAME)
            repo = GitRepository(TABLE_NAME, dynamodb_resource=resource)

            repo.put_user_mapping(
                "user-1",
                {"provider": "github", "gitUsername": "alice", "createdAt": "2024-01-01T00:00:00Z"},
            )

            logger = MagicMock()

            report = migrate(table, logger, lambda: 999_999)

            assert report == {
                "scanned": 0,
                "migrated": 0,
                "discarded": 0,
                "failed": 0,
                "unconverted": 0,
                "truncated": False,
            }

            mappings = repo.list_user_mappings("user-1")
            assert len(mappings) == 1
            assert mappings[0]["gitUsername"] == "alice"


class TestPartiallyMigratedConvergence:
    """A pair holding both a legacy item and a current item — the state a
    crash between `put_item` and `delete_item` leaves behind — converges
    to the single surviving mapping resolved by `select_mapping`, with
    the legacy item removed.
    """

    def test_partially_migrated_pair_converges_to_selected_winner(self):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            table = resource.Table(TABLE_NAME)

            # The legacy item is newer than the current item, so it must
            # win the collapse and become the sole survivor.
            _put_legacy_item(table, "user-1", "github", "zed", created_at="2024-06-01T00:00:00Z")
            table.put_item(
                Item={
                    "PK": "USER#user-1",
                    "SK": mapping_sort_key("github"),
                    "provider": "github",
                    "gitUsername": "alice",
                    "createdAt": "2024-01-01T00:00:00Z",
                }
            )

            logger = MagicMock()

            report = migrate(table, logger, lambda: 999_999)

            assert report["migrated"] == 1
            assert report["discarded"] == 1
            assert report["failed"] == 0

            current_response = table.get_item(Key={"PK": "USER#user-1", "SK": mapping_sort_key("github")})
            assert current_response["Item"]["gitUsername"] == "zed"

            legacy_response = table.get_item(Key={"PK": "USER#user-1", "SK": "GITMAP#github#zed"})
            assert legacy_response.get("Item") is None


class TestWatchdogEarlyStop:
    """The response watchdog stops the loop once the remaining-time
    budget drops below `RESPONSE_MARGIN_MS`, reports a truncated run
    whose counts match the split, and still sends a `SUCCESS` response so
    the stack update is not blocked by a partial migration.
    """

    def test_watchdog_stops_early_and_reports_matching_truncation_counts(self):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            table = resource.Table(TABLE_NAME)

            pairs = [
                ("user-1", "github", "alice"),
                ("user-2", "gitlab", "bob"),
                ("user-3", "github", "carol"),
                ("user-4", "gitlab", "dave"),
            ]
            for user_id, provider, username in pairs:
                _put_legacy_item(table, user_id, provider, username, created_at="2024-01-01T00:00:00Z")

            k = 2
            # A comfortable budget for k items, then a value below the
            # watchdog's margin — a generator so it never exhausts even
            # if the loop checks it more times than there are pairs.
            assert 1_000 < RESPONSE_MARGIN_MS
            remaining_ms_values = itertools.chain(itertools.repeat(60_000, k), itertools.repeat(1_000))
            remaining_ms = lambda: next(remaining_ms_values)  # noqa: E731

            logger = MagicMock()

            report = migrate(table, logger, remaining_ms)

            assert report["truncated"] is True
            assert report["migrated"] == k
            assert report["unconverted"] == len(pairs) - k

            summary_calls = [
                call
                for call in logger.info.call_args_list
                if call.args[0] == "Mapping migration summary"
            ]
            assert len(summary_calls) == 1
            _, summary_kwargs = summary_calls[0]
            assert summary_kwargs["truncated"] is True
            assert summary_kwargs["migrated"] == k
            assert summary_kwargs["unconverted"] == len(pairs) - k

            # The weaker postcondition that survives truncation: every
            # pair present before the run is still retrievable through
            # list_user_mappings, whether it was reached (now under the
            # new key) or not (still under the legacy key).
            repo = GitRepository(TABLE_NAME, dynamodb_resource=resource)
            for user_id, provider, username in pairs:
                remaining = repo.list_user_mappings(user_id)
                assert any(m["gitUsername"] == username for m in remaining)

    def test_watchdog_truncation_still_sends_a_success_response(self):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            table = resource.Table(TABLE_NAME)

            pairs = [
                ("user-1", "github", "alice"),
                ("user-2", "gitlab", "bob"),
                ("user-3", "github", "carol"),
            ]
            for user_id, provider, username in pairs:
                _put_legacy_item(table, user_id, provider, username, created_at="2024-01-01T00:00:00Z")

            k = 1
            # A finite list is safe here: the loop checks remaining_ms()
            # at most once per pair, and this list is longer than that.
            remaining_ms_values = list(
                itertools.chain(itertools.repeat(60_000, k), itertools.repeat(1_000, 10))
            )

            event = _make_event(table_name=TABLE_NAME)
            context = _make_context(remaining_ms_values=remaining_ms_values)

            with patch("boto3.resource", return_value=resource), patch(
                "urllib.request.urlopen"
            ) as mock_urlopen:
                module.lambda_handler(event, context)

            sent_body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
            assert sent_body["Status"] == "SUCCESS"

            data = sent_body["Data"]
            assert data["truncated"] is True
            assert data["migrated"] == k
            assert data["unconverted"] == len(pairs) - k
