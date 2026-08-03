"""ReconcileUsers Lambda handler — reconciles UserNamesTable against IDC.

Invoked by the ETL state machine after RecordStatus. Lists every user in
Identity Center, scans the UserNamesTable, and updates each row's
``status`` / ``tombstonedAt`` / ``lastSeenInIdc`` fields based on whether
the user still exists in IDC.

The handler is fail-safe: any IDC error or empty list aborts the run
without touching the table. Per-row UpdateItem failures are logged and
skipped — they never abort the whole run.
"""

from __future__ import annotations

import datetime
import os

import boto3

try:
    from user_reconciler import build_update_kwargs, classify_row
except ImportError:
    from etl.user_reconciler import build_update_kwargs, classify_row

try:
    from shared.structured_logger import StructuredLogger
except ImportError:
    from utils.logging import StructuredLogger


def _list_idc_user_ids(identity_client, identity_store_id: str) -> set[str]:
    """Fully paginate ``identitystore:ListUsers``.

    Returns the set of all UserIds present in IDC. Raises any exception
    the API returns — the caller is responsible for the fail-safe behavior.
    """
    user_ids: set[str] = set()
    paginator = identity_client.get_paginator("list_users")
    for page in paginator.paginate(IdentityStoreId=identity_store_id):
        for user in page.get("Users", []):
            uid = user.get("UserId")
            if uid:
                user_ids.add(uid)
    return user_ids


def _scan_user_names_table(table) -> list[dict]:
    """Scan the entire UserNamesTable.

    Returns every item with a fully-paginated scan. The table is small
    (one row per Kiro user that has ever generated activity) so a full
    scan is acceptable; if it grows large we can switch to a GSI on
    ``status`` and process tombstone candidates and active candidates
    separately.
    """
    items: list[dict] = []
    kwargs: dict = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def reconcile_users_handler(event, context):  # noqa: ARG001 - Lambda contract
    """ReconcileUsers Lambda entry point.

    Returns a summary dict with counts. The Lambda never raises — any
    error is captured in the summary so the Step Functions Catch sees a
    clean termination. The state machine itself swallows the error path
    via ``Catch: ["States.ALL"]`` so reconcile failures cannot block the
    pipeline.
    """
    logger = StructuredLogger("reconcile-users-lambda")
    today = datetime.date.today().isoformat()

    identity_store_id = os.environ.get("IDENTITY_STORE_ID", "")
    table_name = os.environ.get("USER_NAMES_TABLE", "")

    if not identity_store_id or not table_name:
        logger.error(
            "Reconcile aborted — required env vars missing",
            identityStoreId=bool(identity_store_id),
            userNamesTable=bool(table_name),
        )
        return {
            "status": "skipped",
            "reason": "missing-env-vars",
            "reconciled": 0,
            "tombstoned": 0,
            "restored": 0,
        }

    # ── 1. List IDC users (fail-safe: any error aborts the run) ─────────────
    try:
        identity_client = boto3.client("identitystore")
        idc_user_ids = _list_idc_user_ids(identity_client, identity_store_id)
    except Exception as exc:
        # errorMessage/stackTrace deliberately omitted: this handler is
        # fail-safe by design (see docstring) and never re-raises, so
        # unlike other ETL handlers there is no Step Functions execution
        # history to fall back on for the full exception detail — the
        # structured log is the only place it could land. A ClientError
        # message/traceback can echo ARNs, IdentityStoreId, or other
        # request details beyond what's needed to know *what* failed.
        # errorType (e.g. AccessDeniedException, ThrottlingException) is
        # sufficient to triage.
        logger.error(
            "Reconcile aborted — ListUsers failed",
            errorType=type(exc).__name__,
        )
        return {
            "status": "error",
            "reason": "idc-list-failed",
            "reconciled": 0,
            "tombstoned": 0,
            "restored": 0,
        }

    # ── 2. Empty IDC = misconfiguration. Refuse to tombstone everyone. ──────
    if not idc_user_ids:
        logger.error(
            "Reconcile aborted — IDC returned zero users",
            identityStoreId=identity_store_id,
        )
        return {
            "status": "skipped",
            "reason": "idc-empty",
            "reconciled": 0,
            "tombstoned": 0,
            "restored": 0,
        }

    logger.info(
        "Listed IDC users",
        idcUserCount=len(idc_user_ids),
    )

    # ── 3. Scan UserNamesTable ─────────────────────────────────────────────
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    try:
        rows = _scan_user_names_table(table)
    except Exception as exc:
        # See the ListUsers except block above: this handler never
        # re-raises, so errorMessage/stackTrace are omitted to avoid
        # putting DynamoDB ClientError detail (table ARN, request IDs)
        # into the structured log with no execution-history fallback.
        logger.error(
            "Reconcile aborted — UserNamesTable scan failed",
            errorType=type(exc).__name__,
        )
        return {
            "status": "error",
            "reason": "scan-failed",
            "reconciled": 0,
            "tombstoned": 0,
            "restored": 0,
        }

    # ── 4. Classify and update ─────────────────────────────────────────────
    counters = {
        "update_active": 0,
        "tombstone": 0,
        "restore": 0,
        "noop": 0,
        "update_failed": 0,
    }

    for row in rows:
        user_id = row.get("userId")
        if not user_id:
            continue

        decision = classify_row(row, idc_user_ids, today)

        if decision == "noop":
            counters["noop"] += 1
            continue

        kwargs = build_update_kwargs(user_id, decision, today)
        try:
            table.update_item(**kwargs)
            counters[decision] += 1
        except Exception as exc:
            counters["update_failed"] += 1
            # errorMessage deliberately omitted, consistent with the same
            # pattern applied elsewhere in this change set: a DynamoDB
            # ClientError message can echo request details beyond what's
            # needed here. userId/decision/errorType are sufficient to
            # investigate which user/transition failed and why.
            logger.error(
                "UpdateItem failed for user — continuing",
                userId=user_id,
                decision=decision,
                errorType=type(exc).__name__,
            )

    summary = {
        "status": "ok",
        "reconciled": counters["update_active"]
        + counters["tombstone"]
        + counters["restore"],
        "tombstoned": counters["tombstone"],
        "restored": counters["restore"],
        "noop": counters["noop"],
        "updateFailures": counters["update_failed"],
        "idcUserCount": len(idc_user_ids),
        "tableRowCount": len(rows),
    }
    logger.info("Reconcile complete", **summary)
    return summary
