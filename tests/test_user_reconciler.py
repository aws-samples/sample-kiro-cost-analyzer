"""Tests for ``etl/user_reconciler.py`` — pure logic, no I/O.

The reconciler decides what to do with each UserNamesTable row given
the live IDC user set. These tests pin the four-outcome decision
matrix and the on-wire shape of the resulting UpdateItem expressions.
"""

from __future__ import annotations

import pytest

from etl.user_reconciler import (
    STATUS_ACTIVE,
    STATUS_TOMBSTONED,
    build_update_kwargs,
    classify_row,
)


# ---------------------------------------------------------------------------
# classify_row decision matrix (Requirements 1.4-1.7)
# ---------------------------------------------------------------------------


class TestClassifyRow:
    def test_active_user_in_idc(self) -> None:
        row = {"userId": "u-1", "status": STATUS_ACTIVE}
        assert classify_row(row, {"u-1"}, "2026-05-26") == "update_active"

    def test_user_with_no_status_field_in_idc_treated_as_active(self) -> None:
        # Pre-feature rows have no status field; must default to ACTIVE.
        row = {"userId": "u-1", "displayName": "Old Cache"}
        assert classify_row(row, {"u-1"}, "2026-05-26") == "update_active"

    def test_active_user_removed_from_idc_is_tombstoned(self) -> None:
        row = {"userId": "u-1", "status": STATUS_ACTIVE}
        assert classify_row(row, set(), "2026-05-26") == "tombstone"

    def test_tombstoned_user_back_in_idc_is_restored(self) -> None:
        row = {"userId": "u-1", "status": STATUS_TOMBSTONED}
        assert classify_row(row, {"u-1"}, "2026-05-26") == "restore"

    def test_tombstoned_user_still_absent_is_noop(self) -> None:
        row = {"userId": "u-1", "status": STATUS_TOMBSTONED}
        assert classify_row(row, set(), "2026-05-26") == "noop"


# ---------------------------------------------------------------------------
# build_update_kwargs on-wire shape
# ---------------------------------------------------------------------------


class TestBuildUpdateKwargs:
    def test_update_active_only_touches_lastSeen(self) -> None:
        kwargs = build_update_kwargs("u-1", "update_active", "2026-05-26")
        assert kwargs["Key"] == {"userId": "u-1"}
        # Sets status (lazily upgrades pre-feature rows) and lastSeenInIdc.
        # Does NOT touch displayName/userName/tombstonedAt.
        expr = kwargs["UpdateExpression"]
        assert "SET" in expr
        assert "status" in kwargs["ExpressionAttributeNames"]["#status"]
        assert "lastSeenInIdc" in expr
        # Critically, no REMOVE — we don't want to clear tombstonedAt unless
        # we are restoring.
        assert "REMOVE" not in expr

    def test_restore_clears_tombstonedAt(self) -> None:
        kwargs = build_update_kwargs("u-1", "restore", "2026-05-26")
        expr = kwargs["UpdateExpression"]
        assert "SET" in expr and "REMOVE" in expr
        assert "tombstonedAt" in expr
        assert kwargs["ExpressionAttributeValues"][":active"] == STATUS_ACTIVE

    def test_tombstone_sets_status_and_timestamp(self) -> None:
        kwargs = build_update_kwargs("u-1", "tombstone", "2026-05-26")
        expr = kwargs["UpdateExpression"]
        assert "tombstonedAt" in expr
        assert kwargs["ExpressionAttributeValues"][":tomb"] == STATUS_TOMBSTONED
        assert kwargs["ExpressionAttributeValues"][":today"] == "2026-05-26"

    def test_noop_raises(self) -> None:
        with pytest.raises(ValueError):
            build_update_kwargs("u-1", "noop", "2026-05-26")


# ---------------------------------------------------------------------------
# Properties (Requirement P1, P3, P4)
# ---------------------------------------------------------------------------


class TestProperties:
    def test_history_preserved_across_decisions(self) -> None:
        """Property P3: classify_row never reads displayName or userName,
        and build_update_kwargs never writes them. The reconcile pipeline
        is opaque to the historical fields."""
        row = {
            "userId": "u-1",
            "displayName": "Alice",
            "userName": "alice@co",
            "status": STATUS_ACTIVE,
        }
        # No matter the decision, the kwargs we build never set
        # displayName or userName — so a real DynamoDB update would
        # leave those fields unchanged.
        for in_idc, expected_decision in [
            ({"u-1"}, "update_active"),
            (set(), "tombstone"),
        ]:
            decision = classify_row(row, in_idc, "2026-05-26")
            assert decision == expected_decision
            kwargs = build_update_kwargs("u-1", decision, "2026-05-26")
            expr = kwargs["UpdateExpression"]
            assert "displayName" not in expr
            assert "userName" not in expr

    def test_idempotent_within_run(self) -> None:
        """Property P1 (partial): running classify_row twice on the same
        inputs returns the same decision. The DynamoDB-level idempotence
        is verified by the integration tests."""
        row = {"userId": "u-1", "status": STATUS_ACTIVE}
        decision1 = classify_row(row, {"u-1"}, "2026-05-26")
        decision2 = classify_row(row, {"u-1"}, "2026-05-26")
        assert decision1 == decision2 == "update_active"

    def test_restore_round_trip(self) -> None:
        """Property P4: tombstoning then restoring brings the row back to
        a coherent ACTIVE state. Modeled here at the decision level —
        the integration tests verify the table-level round-trip."""
        # Step 1: row is ACTIVE, user removed from IDC → tombstone.
        row = {"userId": "u-1", "status": STATUS_ACTIVE}
        assert classify_row(row, set(), "2026-05-26") == "tombstone"

        # Step 2: row is now TOMBSTONED, user comes back → restore.
        row = {"userId": "u-1", "status": STATUS_TOMBSTONED, "tombstonedAt": "2026-05-26"}
        assert classify_row(row, {"u-1"}, "2026-06-01") == "restore"

        # Step 3: row is ACTIVE again, user still in IDC → update_active.
        row = {"userId": "u-1", "status": STATUS_ACTIVE}
        assert classify_row(row, {"u-1"}, "2026-06-02") == "update_active"
