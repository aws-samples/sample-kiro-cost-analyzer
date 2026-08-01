"""
CloudFormation Custom Resource Lambda that migrates Git user-to-mapping
items off the Legacy_Mapping_Sort_Key (``GITMAP#{provider}#{gitUsername}``)
onto the current Mapping_Sort_Key (``GITMAP#{provider}``).

Runs once per deployment that introduces or bumps this feature's
``MigrationVersion`` property. Handles Create, Update, and Delete
lifecycle events like ``custom_resources/admin_user_creator.py``; the
actual migration work happens on Create and Update.

See Requirement 11 and design component 14 ("Mapping_Migrator") in
``.kiro/specs/gitlab-provider-support/`` for the full rationale.

Logging note: ``custom_resources/admin_user_creator.py`` logs through the
stdlib ``logging`` module, with plain unstructured messages. This module
diverges from that precedent and uses ``shared.structured_logger
.StructuredLogger`` instead, matching the convention every other Lambda in
this project follows (see the development standards document). The design's
Logging section (component 14) requires named fields per record — userId,
provider, retained gitUsername, discarded count on success; userId and
provider on failure; the full report on the summary record — which is
exactly what ``StructuredLogger.info(message, **fields)`` is for. Threading
those fields through ``%s``-style stdlib messages would work but would not
produce the structured JSON records Requirements 11.7 and 11.8 describe.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

import boto3
from boto3.dynamodb.conditions import Attr

try:
    from git_shared.git_providers import (
        MAPPING_SK_PREFIX,
        is_legacy_mapping_sort_key,
        mapping_sort_key,
    )
except ImportError:
    from layers.shared.git_shared.git_providers import (
        MAPPING_SK_PREFIX,
        is_legacy_mapping_sort_key,
        mapping_sort_key,
    )
try:
    from git_shared.git_mapping_selection import select_mapping
except ImportError:
    from layers.shared.git_shared.git_mapping_selection import select_mapping
try:
    from shared.structured_logger import StructuredLogger
except ImportError:
    from layers.shared.shared.structured_logger import StructuredLogger

logger = StructuredLogger("mapping-migrator")

# Milliseconds reserved for sending the CloudFormation response before the
# execution environment could be torn down at the function timeout. Checked
# between (userId, provider) groups so a single slow group cannot overrun
# the reservation.
RESPONSE_MARGIN_MS = 10_000


def lambda_handler(event, context):
    """Entry point for the Mapping_Migrator CloudFormation Custom Resource."""
    logger.info("Received event", requestType=event.get("RequestType"))

    request_type = event["RequestType"]
    properties = event.get("ResourceProperties", {})
    table_name = properties.get("TableName")
    # Accepted but not used for logic beyond being present in the event —
    # it exists so a template redeploy with a bumped value triggers the
    # Update lifecycle event and re-runs the migration.
    properties.get("MigrationVersion")

    try:
        if request_type in ("Create", "Update"):
            resource = boto3.resource("dynamodb")
            table = resource.Table(table_name)
            report = migrate(table, logger, context.get_remaining_time_in_millis)
            data = {**report, "Message": "Migration complete"}
            _send_response(event, context, "SUCCESS", data)

        elif request_type == "Delete":
            _send_response(event, context, "SUCCESS", {"Message": "No-op on delete"})

        else:
            _send_response(event, context, "FAILED", {"Message": f"Unknown RequestType: {request_type}"})

    except Exception as e:
        # migrate() is contracted to never raise for per-item failures, so
        # this branch guards resource/table setup that happens before
        # migrate() is even called, and the scan itself failing outright
        # (see the Migration Layer error table in the design document).
        logger.error(
            "Error handling custom resource request",
            requestType=request_type,
            errorType=type(e).__name__,
        )
        _send_response(event, context, "FAILED", {"Message": str(e)})


def migrate(table, logger, remaining_ms) -> dict:
    """Convert every legacy mapping item to the current Mapping_Sort_Key.

    Discovers every item whose sort key starts with ``GITMAP#`` via a
    paginated Scan, discriminates legacy items from already-migrated ones
    with ``is_legacy_mapping_sort_key``, groups legacy items by
    ``(userId, provider)`` together with any item already stored under the
    current key for that pair, and resolves each group with the shared
    ``select_mapping`` rule so the migrator and the correlation handler
    can never disagree about which mapping survives.

    For each group the surviving mapping is written under
    ``mapping_sort_key(provider)`` first, and every legacy item in the
    group is deleted only afterward (Requirements 11.2, 11.3, 11.4). A
    stale duplicate already sitting under the current key is overwritten
    in place by that same ``PutItem`` when a different candidate wins, so
    no separate delete is needed for it.

    A failure writing or deleting one group's items is logged with the
    group's userId and provider, counted in ``failed``, and does not stop
    the run (Requirement 11.8). This function never raises for that
    reason; only an exception from the Scan call itself is allowed to
    propagate, since there the run has nothing left to report.

    The loop checks ``remaining_ms()`` between groups (not only once at
    the top, so a single slow group cannot overrun the reservation) and
    stops cleanly, marking the run ``truncated``, once the budget drops
    below ``RESPONSE_MARGIN_MS``.

    Args:
        table: A boto3 DynamoDB Table resource for the Analytics table.
        logger: A ``StructuredLogger`` (or compatible test double exposing
            ``.info(message, **fields)`` / ``.error(...)`` /
            ``.warning(...)``) used for per-pair, per-failure, and summary
            log records.
        remaining_ms: Zero-argument callable returning the milliseconds
            left in the invocation, e.g.
            ``context.get_remaining_time_in_millis``.

    Returns:
        A report dict: ``{scanned, migrated, discarded, failed,
        unconverted, truncated}``.

        - ``scanned``: total legacy items discovered by the scan.
        - ``migrated``: number of (userId, provider) pairs successfully
          migrated to the current key.
        - ``discarded``: number of candidate items (legacy items, plus a
          stale current-key item when one existed) that lost the
          selection across all successfully migrated pairs.
        - ``failed``: number of pairs whose migration raised while
          writing or deleting items.
        - ``unconverted``: number of legacy items left unmigrated, either
          because their pair's migration raised or because the watchdog
          truncated the run before their pair was reached.
        - ``truncated``: True if the response watchdog stopped the loop
          before every group was processed.
    """
    report = {
        "scanned": 0,
        "migrated": 0,
        "discarded": 0,
        "failed": 0,
        "unconverted": 0,
        "truncated": False,
    }

    groups = _scan_legacy_groups(table)
    report["scanned"] = sum(len(group["legacy_items"]) for group in groups)

    for index, group in enumerate(groups):
        if remaining_ms() < RESPONSE_MARGIN_MS:
            report["truncated"] = True
            report["unconverted"] += sum(
                len(remaining_group["legacy_items"]) for remaining_group in groups[index:]
            )
            logger.warning(
                "Mapping migration truncated: response time budget exhausted",
                pairsRemaining=len(groups) - index,
                pairsTotal=len(groups),
            )
            break
        _migrate_group(table, logger, group, report)

    logger.info(
        "Mapping migration summary",
        scanned=report["scanned"],
        migrated=report["migrated"],
        discarded=report["discarded"],
        failed=report["failed"],
        unconverted=report["unconverted"],
        truncated=report["truncated"],
    )
    return report


def _scan_legacy_groups(table) -> list[dict]:
    """Scan every ``GITMAP#`` item and group legacy items by (userId, provider).

    Args:
        table: A boto3 DynamoDB Table resource.

    Returns:
        A list of group dicts, one per (userId, provider) pair that has at
        least one legacy item: ``{"user_id", "provider", "legacy_items",
        "current_item"}``, where ``current_item`` is the item already
        stored under the current key for that pair, or None.
    """
    legacy_by_pair: dict[tuple[str, str], list[dict]] = {}
    current_by_pair: dict[tuple[str, str], dict] = {}

    scan_kwargs: dict = {"FilterExpression": Attr("SK").begins_with(MAPPING_SK_PREFIX)}
    while True:
        response = table.scan(**scan_kwargs)
        for item in response.get("Items", []):
            user_id = _user_id_from_pk(item.get("PK", ""))
            sort_key = item.get("SK", "")
            provider = _resolve_provider(item, sort_key)
            pair = (user_id, provider)
            if is_legacy_mapping_sort_key(sort_key):
                legacy_by_pair.setdefault(pair, []).append(item)
            else:
                current_by_pair[pair] = item

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    return [
        {
            "user_id": user_id,
            "provider": provider,
            "legacy_items": legacy_items,
            "current_item": current_by_pair.get((user_id, provider)),
        }
        for (user_id, provider), legacy_items in legacy_by_pair.items()
    ]


def _migrate_group(table, logger, group: dict, report: dict) -> None:
    """Collapse and migrate one (userId, provider) group in place.

    Resolves the surviving mapping with ``select_mapping`` over the
    group's legacy items plus any item already under the current key,
    writes the winner under the current key, then deletes every legacy
    item in the group. Updates ``report`` in place; never raises.

    Args:
        table: A boto3 DynamoDB Table resource.
        logger: Logger used for the per-pair and per-failure records.
        group: One group dict as produced by ``_scan_legacy_groups``.
        report: The running report dict to update.
    """
    user_id = group["user_id"]
    provider = group["provider"]
    legacy_items = group["legacy_items"]
    current_item = group["current_item"]

    candidates = list(legacy_items)
    if current_item is not None:
        candidates.append(current_item)

    winner = select_mapping(candidates)

    new_item = {
        "PK": f"USER#{user_id}",
        "SK": mapping_sort_key(provider),
        "provider": provider,
        "gitUsername": winner.get("gitUsername"),
    }
    if "createdAt" in winner:
        new_item["createdAt"] = winner["createdAt"]
    if "createdBy" in winner:
        new_item["createdBy"] = winner["createdBy"]

    try:
        # Put first, then delete: a crash between the two leaves a
        # duplicate a re-run collapses, rather than losing the mapping
        # with no record of what it was.
        table.put_item(Item=new_item)
        for legacy_item in legacy_items:
            table.delete_item(Key={"PK": legacy_item["PK"], "SK": legacy_item["SK"]})
    except Exception as exc:
        report["failed"] += 1
        report["unconverted"] += len(legacy_items)
        logger.error(
            "Failed to migrate mapping",
            userId=user_id,
            provider=provider,
            errorType=type(exc).__name__,
        )
        return

    discarded_count = len(candidates) - 1
    report["migrated"] += 1
    report["discarded"] += discarded_count

    logger.info(
        "Migrated mapping",
        userId=user_id,
        provider=provider,
        gitUsername=new_item["gitUsername"],
        discarded=discarded_count,
    )


def _user_id_from_pk(partition_key: str) -> str:
    """Extract the Kiro userId from a ``USER#{userId}`` partition key."""
    prefix = "USER#"
    if partition_key.startswith(prefix):
        return partition_key[len(prefix):]
    return partition_key


def _resolve_provider(item: dict, sort_key: str) -> str:
    """Resolve a mapping item's provider from its attribute or its sort key.

    Args:
        item: The raw DynamoDB item.
        sort_key: The item's SK value, shaped either as
            ``GITMAP#{provider}`` or ``GITMAP#{provider}#{gitUsername}``.

    Returns:
        The item's ``provider`` attribute when present, otherwise the
        second ``#``-separated segment of the sort key (e.g.
        ``GITMAP#gitlab#alice`` -> ``gitlab``).
    """
    provider = item.get("provider")
    if provider:
        return provider
    segments = sort_key.split("#")
    return segments[1] if len(segments) > 1 else ""


def _send_response(event, context, status, data):
    """Send response back to CloudFormation."""
    response_url = event["ResponseURL"]

    # Validate URL scheme — only HTTPS is permitted for CloudFormation
    # custom resource callbacks (mitigates Bandit B310).
    parsed = urllib.parse.urlparse(response_url)
    if parsed.scheme != "https":
        raise ValueError(f"Refusing to send response to non-HTTPS URL: {parsed.scheme}")

    response_body = json.dumps({
        "Status": status,
        "Reason": data.get("Message", "See CloudWatch logs"),
        "PhysicalResourceId": event.get("PhysicalResourceId", context.log_stream_name),
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data,
    })

    logger.info("Sending response to CloudFormation", status=status)

    req = urllib.request.Request(
        url=response_url,
        data=response_body.encode("utf-8"),
        headers={"Content-Type": ""},
        method="PUT",
    )
    urllib.request.urlopen(req)  # noqa: S310 — URL scheme validated above
