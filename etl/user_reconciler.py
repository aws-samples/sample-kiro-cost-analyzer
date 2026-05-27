"""Pure logic for reconciling UserNamesTable rows against Identity Center.

Two pure functions encapsulate the entire decision tree:

- :func:`classify_row` decides what to do with a row given the live IDC
  user set.
- :func:`build_update_kwargs` builds a DynamoDB ``UpdateItem`` kwargs
  dict for a non-noop decision.

Both are testable without mocks, without boto3, and without I/O. The
Lambda handler that orchestrates them lives in
``etl/reconcile_users_handler.py``.
"""

from __future__ import annotations

from typing import Literal

Decision = Literal["update_active", "tombstone", "restore", "noop"]

STATUS_ACTIVE = "ACTIVE"
STATUS_TOMBSTONED = "TOMBSTONED"


def classify_row(row: dict, idc_user_ids: set[str], today: str) -> Decision:
    """Decide what to do with a single UserNamesTable row.

    The four outcomes are mutually exclusive and cover every combination
    of (presence in IDC) × (current status). Missing ``status`` is
    treated as ``ACTIVE`` for backward compatibility with rows written
    before this feature.

    Args:
        row: The DynamoDB item. Must contain ``userId``; ``status`` is
            optional and defaults to ``ACTIVE``.
        idc_user_ids: Set of userIds returned by ``identitystore:ListUsers``.
        today: ISO date string. Unused by ``classify_row`` itself but
            accepted to keep ``build_update_kwargs`` and this function
            signature-symmetric, which simplifies the orchestrator loop.

    Returns:
        - ``"update_active"`` — user in IDC, status is ACTIVE/missing.
          Update ``lastSeenInIdc`` only.
        - ``"restore"`` — user in IDC, status is TOMBSTONED.
          Flip back to ACTIVE, clear ``tombstonedAt``.
        - ``"tombstone"`` — user not in IDC, status is ACTIVE/missing.
          Mark TOMBSTONED, set ``tombstonedAt``.
        - ``"noop"`` — user not in IDC, status is already TOMBSTONED.
    """
    del today  # symmetric with build_update_kwargs; not consumed here

    user_id = row["userId"]
    status = row.get("status", STATUS_ACTIVE)
    in_idc = user_id in idc_user_ids

    if in_idc and status != STATUS_TOMBSTONED:
        return "update_active"
    if in_idc and status == STATUS_TOMBSTONED:
        return "restore"
    if not in_idc and status != STATUS_TOMBSTONED:
        return "tombstone"
    return "noop"


def build_update_kwargs(user_id: str, decision: Decision, today: str) -> dict:
    """Build the kwargs for ``Table.update_item`` for a given decision.

    The caller is expected to pass these kwargs verbatim to boto3.
    Centralizing the expressions here means the on-wire shape of the
    row lives in exactly one place and is the contract the tests pin.

    Args:
        user_id: The row's primary key.
        decision: Output of :func:`classify_row`. Must not be ``"noop"``
            (the orchestrator filters those out before calling this).
        today: ISO date string used for ``lastSeenInIdc`` and
            ``tombstonedAt``.

    Returns:
        Dict suitable for ``table.update_item(**kwargs)``.

    Raises:
        ValueError: If ``decision`` is ``"noop"`` (caller bug).
    """
    if decision == "noop":
        raise ValueError("noop decisions must be filtered out before calling build_update_kwargs")

    base: dict = {"Key": {"userId": user_id}}

    if decision == "update_active":
        # No status flip — only refresh the lastSeenInIdc timestamp. We
        # also SET status=ACTIVE to lazily upgrade pre-feature rows
        # whose status field was missing.
        base["UpdateExpression"] = "SET #status = :active, lastSeenInIdc = :today"
        base["ExpressionAttributeNames"] = {"#status": "status"}
        base["ExpressionAttributeValues"] = {
            ":active": STATUS_ACTIVE,
            ":today": today,
        }
        return base

    if decision == "restore":
        # Coming back from tombstone — flip status, clear tombstonedAt.
        base["UpdateExpression"] = (
            "SET #status = :active, lastSeenInIdc = :today REMOVE tombstonedAt"
        )
        base["ExpressionAttributeNames"] = {"#status": "status"}
        base["ExpressionAttributeValues"] = {
            ":active": STATUS_ACTIVE,
            ":today": today,
        }
        return base

    # decision == "tombstone"
    base["UpdateExpression"] = "SET #status = :tomb, tombstonedAt = :today"
    base["ExpressionAttributeNames"] = {"#status": "status"}
    base["ExpressionAttributeValues"] = {
        ":tomb": STATUS_TOMBSTONED,
        ":today": today,
    }
    return base
