"""Tests for etl.csv_parser module."""

import logging

import pytest

from etl.csv_parser import combine_records, parse_csv


# ---------------------------------------------------------------------------
# parse_csv — New Format
# ---------------------------------------------------------------------------

NEW_FORMAT_HEADER = (
    "Date,UserId,Client_Type,Subscription_Tier,ProfileId,"
    "Total_Messages,Chat_Conversations,Credits_Used,"
    "Overage_Enabled,Overage_Cap,Overage_Credits_Used"
)

NEW_FORMAT_ROW = (
    '2026-04-02,"user-1",KIRO_IDE,PRO_PLUS,'
    '"arn:aws:codewhisperer:us-east-1:123:profile/ABC",'
    "36,2,4.77,true,10000.0,0.0"
)


class TestParseCsvNewFormat:
    def test_parses_single_row(self):
        content = f"{NEW_FORMAT_HEADER}\n{NEW_FORMAT_ROW}\n"
        records = parse_csv(content, "new")

        assert len(records) == 1
        r = records[0]
        assert r["Date"] == "2026-04-02"
        assert r["UserId"] == "user-1"
        assert r["Client_Type"] == "KIRO_IDE"
        assert r["Credits_Used"] == "4.77"
        assert r["Total_Messages"] == "36"
        assert r["Chat_Conversations"] == "2"

    def test_parses_multiple_rows(self):
        row2 = '2026-04-03,"user-2",KIRO_CLI,PRO,"arn:profile/DEF",10,1,2.5,false,0,0'
        content = f"{NEW_FORMAT_HEADER}\n{NEW_FORMAT_ROW}\n{row2}\n"
        records = parse_csv(content, "new")

        assert len(records) == 2
        assert records[0]["UserId"] == "user-1"
        assert records[1]["UserId"] == "user-2"


# ---------------------------------------------------------------------------
# parse_csv — Legacy Format
# ---------------------------------------------------------------------------

LEGACY_HEADER = (
    "Date,UserId,Client_Type,Subscription_Tier,ProfileId,"
    "Chat_AICodeLines,Chat_MessagesSent,Inline_AICodeLines"
)

LEGACY_ROW = (
    '2025-12-01,"user-legacy",KIRO_IDE,PRO,'
    '"arn:profile/OLD",100,50,200'
)


class TestParseCsvLegacyFormat:
    def test_legacy_format_returns_empty(self):
        """Legacy format without Credits_Used column is unsupported and returns empty."""
        content = f"{LEGACY_HEADER}\n{LEGACY_ROW}\n"
        records = parse_csv(content, "legacy")

        assert records == []

    def test_legacy_without_path_hint_returns_empty(self):
        """Legacy format without Credits_Used column returns empty regardless of path hint."""
        content = f"{LEGACY_HEADER}\n{LEGACY_ROW}\n"
        records = parse_csv(content, "")

        assert records == []


# ---------------------------------------------------------------------------
# parse_csv — Edge cases
# ---------------------------------------------------------------------------

class TestParseCsvEdgeCases:
    def test_empty_string_returns_empty(self):
        assert parse_csv("", "new") == []

    def test_whitespace_only_returns_empty(self):
        assert parse_csv("   \n  ", "new") == []

    def test_header_only_returns_empty(self):
        content = f"{NEW_FORMAT_HEADER}\n"
        assert parse_csv(content, "new") == []

    def test_unknown_format_returns_empty_and_logs(self, caplog):
        content = "Foo,Bar\n1,2\n"
        with caplog.at_level(logging.ERROR):
            records = parse_csv(content, "")

        assert records == []
        # Schema validation runs first and catches missing critical columns
        # before the legacy ``Credits_Used`` check. Both paths return an
        # empty list — the test only cares that the parser fails closed
        # and emits a structured ERROR log.
        assert "CSV schema validation failed" in caplog.text
        assert "Credits_Used" in caplog.text

    def test_quoted_fields_parsed_correctly(self):
        row = (
            '2026-04-02,"user,with,commas",KIRO_IDE,PRO_PLUS,'
            '"arn:profile/X",10,1,3.0,true,500.0,0.0'
        )
        content = f"{NEW_FORMAT_HEADER}\n{row}\n"
        records = parse_csv(content, "new")

        assert len(records) == 1
        assert records[0]["UserId"] == "user,with,commas"


# ---------------------------------------------------------------------------
# combine_records
# ---------------------------------------------------------------------------

class TestCombineRecords:
    def test_combines_multiple_parts(self):
        part1 = [{"a": "1"}, {"a": "2"}]
        part2 = [{"a": "3"}]
        part3 = [{"a": "4"}, {"a": "5"}, {"a": "6"}]

        result = combine_records([part1, part2, part3])

        assert len(result) == 6
        assert result == [{"a": "1"}, {"a": "2"}, {"a": "3"}, {"a": "4"}, {"a": "5"}, {"a": "6"}]

    def test_empty_parts(self):
        assert combine_records([]) == []

    def test_parts_with_empty_lists(self):
        result = combine_records([[], [{"x": "1"}], []])
        assert len(result) == 1

    def test_single_part(self):
        part = [{"k": "v"}]
        result = combine_records([part])
        assert result == [{"k": "v"}]
