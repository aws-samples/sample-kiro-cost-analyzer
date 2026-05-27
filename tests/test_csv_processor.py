"""Tests for etl.processors.csv_processor module."""

import pytest

from etl.processors.csv_processor import process_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NEW_FORMAT_HEADER = (
    "Date,UserId,Client_Type,Subscription_Tier,ProfileId,"
    "Total_Messages,Chat_Conversations,Credits_Used,"
    "Overage_Enabled,Overage_Cap,Overage_Credits_Used"
)

NEW_FORMAT_ROW = (
    '2026-04-02,"user-1",KIRO_IDE,PRO_PLUS,'
    '"arn:aws:codewhisperer:us-east-1:123:profile/ABC",'
    "36,2,4.77,true,10000.0,0.5"
)

METADATA = {"region": "us-east-1", "account_id": "123456789012", "client_type": "KIRO_IDE"}


# ---------------------------------------------------------------------------
# process_csv — happy path
# ---------------------------------------------------------------------------

class TestProcessCsvHappyPath:
    def test_single_row_returns_one_record(self):
        content = f"{NEW_FORMAT_HEADER}\n{NEW_FORMAT_ROW}\n"
        result = process_csv(content, "new", METADATA)

        assert len(result) == 1

    def test_record_has_required_dynamo_fields(self):
        content = f"{NEW_FORMAT_HEADER}\n{NEW_FORMAT_ROW}\n"
        result = process_csv(content, "new", METADATA)
        rec = result[0]

        assert rec["userId"] == "user-1"
        assert rec["date"] == "2026-04-02"
        assert rec["totalCredits"] == pytest.approx(4.77)
        assert rec["overageCredits"] == pytest.approx(0.5)
        assert rec["totalMessages"] == 36
        assert rec["totalConversations"] == 2
        assert rec["totalInteractions"] == 38  # 36 + 2

    def test_record_includes_metadata_fields(self):
        content = f"{NEW_FORMAT_HEADER}\n{NEW_FORMAT_ROW}\n"
        result = process_csv(content, "new", METADATA)
        rec = result[0]

        assert rec["clientType"] == "KIRO_IDE"
        assert rec["subscriptionTier"] == "PRO_PLUS"
        assert rec["region"] == "us-east-1"
        assert rec["accountId"] == "123456789012"

    def test_multiple_rows(self):
        row2 = '2026-04-03,"user-2",KIRO_CLI,PRO,"arn:profile/DEF",10,1,2.5,false,0,0'
        content = f"{NEW_FORMAT_HEADER}\n{NEW_FORMAT_ROW}\n{row2}\n"
        result = process_csv(content, "new", METADATA)

        assert len(result) == 2
        assert result[0]["userId"] == "user-1"
        assert result[1]["userId"] == "user-2"
        assert result[1]["totalCredits"] == pytest.approx(2.5)
        assert result[1]["totalMessages"] == 10


# ---------------------------------------------------------------------------
# process_csv — edge cases
# ---------------------------------------------------------------------------

class TestProcessCsvEdgeCases:
    def test_empty_content_returns_empty(self):
        assert process_csv("", "new", METADATA) == []

    def test_whitespace_only_returns_empty(self):
        assert process_csv("   \n  ", "new", METADATA) == []

    def test_header_only_returns_empty(self):
        content = f"{NEW_FORMAT_HEADER}\n"
        assert process_csv(content, "new", METADATA) == []

    def test_unsupported_format_returns_empty(self):
        content = "Foo,Bar\n1,2\n"
        assert process_csv(content, "new", {}) == []

    def test_empty_metadata_uses_defaults(self):
        content = f"{NEW_FORMAT_HEADER}\n{NEW_FORMAT_ROW}\n"
        result = process_csv(content, "new", {})
        rec = result[0]

        assert rec["region"] == ""
        assert rec["accountId"] == ""

    def test_missing_numeric_fields_default_to_zero(self):
        row = '2026-04-02,"user-x",KIRO_IDE,PRO,"",,,,,,'
        content = f"{NEW_FORMAT_HEADER}\n{row}\n"
        result = process_csv(content, "new", METADATA)
        rec = result[0]

        assert rec["totalCredits"] == 0.0
        assert rec["overageCredits"] == 0.0
        assert rec["totalMessages"] == 0
        assert rec["totalConversations"] == 0
        assert rec["totalInteractions"] == 0

    def test_client_type_fallback_from_metadata(self):
        row = '2026-04-02,"user-y",,PRO,"",10,1,2.0,false,0,0'
        content = f"{NEW_FORMAT_HEADER}\n{row}\n"
        result = process_csv(content, "new", {"client_type": "KIRO_CLI"})
        rec = result[0]

        assert rec["clientType"] == "KIRO_CLI"
