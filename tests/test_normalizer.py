"""Tests for etl.normalizer module."""

import pytest

from etl.normalizer import UserActivityRecord, normalize_records


# ---------------------------------------------------------------------------
# New format normalization
# ---------------------------------------------------------------------------

class TestNormalizeNewFormat:
    def test_full_record(self):
        raw = {
            "Date": "2026-04-02",
            "UserId": "user-1",
            "Client_Type": "KIRO_IDE",
            "Subscription_Tier": "PRO_PLUS",
            "ProfileId": "arn:aws:profile/ABC",
            "Total_Messages": "36",
            "Chat_Conversations": "2",
            "Credits_Used": "4.77",
            "Overage_Enabled": "true",
            "Overage_Cap": "10000.0",
            "Overage_Credits_Used": "0.0",
        }
        results = normalize_records([raw], "new")

        assert len(results) == 1
        r = results[0]
        assert isinstance(r, UserActivityRecord)
        assert r.userId == "user-1"
        assert r.date == "2026-04-02"
        assert r.clientType == "KIRO_IDE"
        assert r.subscriptionTier == "PRO_PLUS"
        assert r.profileId == "arn:aws:profile/ABC"
        assert r.totalMessages == 36
        assert r.chatConversations == 2
        assert r.creditsUsed == pytest.approx(4.77)
        assert r.overageEnabled is True
        assert r.overageCap == pytest.approx(10000.0)
        assert r.overageCreditsUsed == pytest.approx(0.0)

    def test_client_type_fallback_from_path_metadata(self):
        raw = {
            "Date": "2026-04-02",
            "UserId": "user-2",
            "Client_Type": "",
            "Subscription_Tier": "PRO",
            "ProfileId": "arn:profile/X",
            "Total_Messages": "10",
            "Chat_Conversations": "1",
            "Credits_Used": "2.5",
            "Overage_Enabled": "false",
            "Overage_Cap": "0",
            "Overage_Credits_Used": "0",
        }
        metadata = {"client_type": "KIRO_CLI", "format_type": "new"}
        results = normalize_records([raw], "new", metadata)

        assert results[0].clientType == "KIRO_CLI"

    def test_client_type_csv_takes_precedence_over_path(self):
        raw = {
            "Date": "2026-04-02",
            "UserId": "user-3",
            "Client_Type": "PLUGIN",
            "Subscription_Tier": "POWER",
            "ProfileId": "",
            "Total_Messages": "5",
            "Chat_Conversations": "0",
            "Credits_Used": "1.0",
            "Overage_Enabled": "false",
            "Overage_Cap": "0",
            "Overage_Credits_Used": "0",
        }
        metadata = {"client_type": "KIRO_IDE"}
        results = normalize_records([raw], "new", metadata)

        assert results[0].clientType == "PLUGIN"

    def test_missing_numeric_fields_default_to_zero(self):
        raw = {
            "Date": "2026-04-02",
            "UserId": "user-4",
            "Client_Type": "KIRO_IDE",
            "Subscription_Tier": "PRO",
            "ProfileId": "",
        }
        results = normalize_records([raw], "new")
        r = results[0]

        assert r.totalMessages == 0
        assert r.chatConversations == 0
        assert r.creditsUsed == 0.0
        assert r.overageEnabled is False
        assert r.overageCap == 0.0
        assert r.overageCreditsUsed == 0.0

    def test_no_path_metadata(self):
        raw = {
            "Date": "2026-04-02",
            "UserId": "user-5",
            "Client_Type": "",
            "Subscription_Tier": "PRO",
            "ProfileId": "",
            "Total_Messages": "1",
            "Chat_Conversations": "0",
            "Credits_Used": "0.5",
            "Overage_Enabled": "false",
            "Overage_Cap": "0",
            "Overage_Credits_Used": "0",
        }
        results = normalize_records([raw], "new", None)

        assert results[0].clientType == ""


# ---------------------------------------------------------------------------
# Legacy format normalization
# ---------------------------------------------------------------------------

class TestNormalizeLegacyFormat:
    def test_legacy_record_returns_defaults_for_unmapped_columns(self):
        """Legacy format columns (Chat_MessagesSent etc.) are not mapped — values default to 0."""
        raw = {
            "Date": "2025-12-01",
            "UserId": "user-legacy",
            "Client_Type": "KIRO_IDE",
            "Subscription_Tier": "PRO",
            "ProfileId": "arn:profile/OLD",
            "Chat_AICodeLines": "100",
            "Chat_MessagesSent": "50",
            "Inline_AICodeLines": "200",
        }
        results = normalize_records([raw], "legacy")

        assert len(results) == 1
        r = results[0]
        assert r.userId == "user-legacy"
        assert r.date == "2025-12-01"
        assert r.clientType == "KIRO_IDE"
        assert r.subscriptionTier == "PRO"
        assert r.totalMessages == 0  # legacy columns not mapped
        assert r.chatConversations == 0
        assert r.creditsUsed == 0.0
        assert r.overageEnabled is False
        assert r.overageCap == 0.0
        assert r.overageCreditsUsed == 0.0

    def test_legacy_missing_chat_messages_sent(self):
        raw = {
            "Date": "2025-11-15",
            "UserId": "user-no-msgs",
            "Client_Type": "",
            "Subscription_Tier": "",
            "ProfileId": "",
        }
        results = normalize_records([raw], "legacy")
        r = results[0]

        assert r.totalMessages == 0
        assert r.clientType == ""
        assert r.subscriptionTier == ""


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestNormalizeEdgeCases:
    def test_empty_list(self):
        assert normalize_records([], "new") == []
        assert normalize_records([], "legacy") == []

    def test_multiple_records(self):
        recs = [
            {"Date": "2026-01-01", "UserId": "a", "Client_Type": "KIRO_IDE",
             "Subscription_Tier": "PRO", "ProfileId": "", "Total_Messages": "10",
             "Chat_Conversations": "1", "Credits_Used": "2.0",
             "Overage_Enabled": "false", "Overage_Cap": "0", "Overage_Credits_Used": "0"},
            {"Date": "2026-01-02", "UserId": "b", "Client_Type": "KIRO_CLI",
             "Subscription_Tier": "POWER", "ProfileId": "", "Total_Messages": "20",
             "Chat_Conversations": "3", "Credits_Used": "5.0",
             "Overage_Enabled": "true", "Overage_Cap": "100", "Overage_Credits_Used": "1.5"},
        ]
        results = normalize_records(recs, "new")

        assert len(results) == 2
        assert results[0].userId == "a"
        assert results[1].userId == "b"
        assert results[1].overageEnabled is True
        assert results[1].overageCreditsUsed == pytest.approx(1.5)

    def test_invalid_numeric_values_default_gracefully(self):
        raw = {
            "Date": "2026-04-02",
            "UserId": "user-bad",
            "Client_Type": "KIRO_IDE",
            "Subscription_Tier": "PRO",
            "ProfileId": "",
            "Total_Messages": "not_a_number",
            "Chat_Conversations": "",
            "Credits_Used": "abc",
            "Overage_Enabled": "maybe",
            "Overage_Cap": "???",
            "Overage_Credits_Used": "",
        }
        results = normalize_records([raw], "new")
        r = results[0]

        assert r.totalMessages == 0
        assert r.chatConversations == 0
        assert r.creditsUsed == 0.0
        assert r.overageEnabled is False
        assert r.overageCap == 0.0
        assert r.overageCreditsUsed == 0.0
