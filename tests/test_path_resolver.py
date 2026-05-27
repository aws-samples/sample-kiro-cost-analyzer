"""Tests for etl.path_resolver module."""

import pytest

from etl.path_resolver import resolve_path_metadata

PREFIX = "activities/AWSLogs/673826570926/KiroLogs/"


class TestLegacyPath:
    def test_legacy_path_returns_none(self):
        """Legacy by_user_analytic paths are no longer supported and return None."""
        key = f"{PREFIX}by_user_analytic/us-east-1/2026/01/28/00/673826570926_by_user_analytic_202601280000_report.csv"
        result = resolve_path_metadata(key, PREFIX)

        assert result is None

    def test_legacy_different_region_returns_none(self):
        key = f"{PREFIX}by_user_analytic/eu-west-1/2025/12/05/00/111222333444_by_user_analytic_202512050000_report.csv"
        result = resolve_path_metadata(key, PREFIX)

        assert result is None


class TestNewPath:
    def test_extracts_metadata_from_new_path_kiro_ide(self):
        key = f"{PREFIX}user_report/us-east-1/2026/04/02/00/KIRO_IDE_673826570926_user_report_202604020000.csv"
        result = resolve_path_metadata(key, PREFIX)

        assert result is not None
        assert result["format_type"] == "new"
        assert result["region"] == "us-east-1"
        assert result["year"] == "2026"
        assert result["month"] == "04"
        assert result["day"] == "02"
        assert result["account_id"] == "673826570926"
        assert result["client_type"] == "KIRO_IDE"

    def test_extracts_metadata_from_new_path_kiro_cli(self):
        key = f"{PREFIX}user_report/us-west-2/2026/03/15/00/KIRO_CLI_999888777666_user_report_202603150000.csv"
        result = resolve_path_metadata(key, PREFIX)

        assert result["format_type"] == "new"
        assert result["region"] == "us-west-2"
        assert result["account_id"] == "999888777666"
        assert result["client_type"] == "KIRO_CLI"

    def test_extracts_single_word_client_type(self):
        key = f"{PREFIX}user_report/us-east-1/2026/05/10/00/PLUGIN_123456789012_user_report_202605100000.csv"
        result = resolve_path_metadata(key, PREFIX)

        assert result["client_type"] == "PLUGIN"
        assert result["account_id"] == "123456789012"


class TestUnrecognizedPaths:
    def test_returns_none_for_uuid_path(self):
        key = f"{PREFIX}2d5eb9bb-703f-40d6-b6d9-2df4b0eeff1d/some_file.csv"
        result = resolve_path_metadata(key, PREFIX)

        assert result is None

    def test_returns_none_for_completely_different_path(self):
        key = "some/other/random/path.csv"
        result = resolve_path_metadata(key, PREFIX)

        assert result is None

    def test_returns_none_for_empty_relative_path(self):
        result = resolve_path_metadata(PREFIX, PREFIX)

        assert result is None

    def test_returns_none_for_short_legacy_path(self):
        key = f"{PREFIX}by_user_analytic/us-east-1/2026"
        result = resolve_path_metadata(key, PREFIX)

        assert result is None

    def test_returns_none_for_short_new_path(self):
        key = f"{PREFIX}user_report/us-east-1"
        result = resolve_path_metadata(key, PREFIX)

        assert result is None
