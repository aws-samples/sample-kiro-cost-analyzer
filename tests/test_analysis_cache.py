"""Tests for AnalyticsRepository analysis cache methods (Group 5)."""

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from repository.analytics_repository import AnalyticsRepository


@pytest.fixture
def mock_table():
    table = MagicMock()
    return table


@pytest.fixture
def repo(mock_table):
    with patch("boto3.resource") as mock_resource:
        mock_resource.return_value.Table.return_value = mock_table
        r = AnalyticsRepository("TestTable")
        r._table = mock_table
        return r


class TestPutAnalysis:
    def test_persists_correctly(self, repo, mock_table):
        mock_table.put_item.return_value = {}

        result = repo.put_analysis("user1", {
            "impactScore": 72,
            "impactLevel": "high",
            "correlations": [],
            "insights": ["Insight 1"],
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": "2026-05-05T14:30:00Z",
            "model": "global.anthropic.claude-sonnet-4-6-v1",
            "tokensUsed": 4200,
        })

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == "USER#user1"
        assert item["SK"].startswith("ANALYSIS#2026-05-05#")
        assert item["impactScore"] == Decimal("72")
        assert "TTL" in item

    def test_ttl_is_7_days(self, repo, mock_table):
        mock_table.put_item.return_value = {}
        now = time.time()

        repo.put_analysis("user1", {
            "impactScore": 50,
            "impactLevel": "moderate",
            "correlations": [],
            "insights": [],
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "analyzedAt": "2026-05-05T14:30:00Z",
        })

        item = mock_table.put_item.call_args[1]["Item"]
        ttl = int(item["TTL"])
        expected_min = int(now) + (7 * 86400) - 5
        expected_max = int(now) + (7 * 86400) + 5
        assert expected_min <= ttl <= expected_max


class TestGetLatestAnalysis:
    def test_returns_none_when_no_items(self, repo, mock_table):
        mock_table.query.return_value = {"Items": []}
        result = repo.get_latest_analysis("user1")
        assert result is None

    def test_returns_none_when_cache_expired(self, repo, mock_table):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        mock_table.query.return_value = {
            "Items": [{
                "PK": "USER#user1",
                "SK": "ANALYSIS#2026-05-04#abc123",
                "analyzedAt": old_time,
                "TTL": Decimal(str(int(time.time()) + 86400)),
                "period": {"startDate": "2026-04-28", "endDate": "2026-05-04"},
            }]
        }
        result = repo.get_latest_analysis("user1")
        assert result is None

    def test_returns_data_when_cache_valid(self, repo, mock_table):
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mock_table.query.return_value = {
            "Items": [{
                "PK": "USER#user1",
                "SK": "ANALYSIS#2026-05-05#abc123",
                "analyzedAt": recent_time,
                "impactScore": Decimal("72"),
                "impactLevel": "high",
                "TTL": Decimal(str(int(time.time()) + 86400 * 6)),
                "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            }]
        }
        result = repo.get_latest_analysis(
            "user1", start_date="2026-04-28", end_date="2026-05-05"
        )
        assert result is not None
        assert result["impactScore"] == 72

    def test_returns_none_when_period_mismatch(self, repo, mock_table):
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        mock_table.query.return_value = {
            "Items": [{
                "PK": "USER#user1",
                "SK": "ANALYSIS#2026-05-05#abc123",
                "analyzedAt": recent_time,
                "TTL": Decimal(str(int(time.time()) + 86400 * 6)),
                "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            }]
        }
        result = repo.get_latest_analysis(
            "user1", start_date="2026-04-20", end_date="2026-04-27"
        )
        assert result is None


class TestListAnalyses:
    def test_returns_list(self, repo, mock_table):
        mock_table.query.return_value = {
            "Items": [
                {"PK": "USER#user1", "SK": "ANALYSIS#2026-05-05#a", "impactScore": Decimal("72")},
                {"PK": "USER#user1", "SK": "ANALYSIS#2026-05-04#b", "impactScore": Decimal("65")},
            ]
        }
        result = repo.list_analyses("user1", limit=10)
        assert len(result) == 2
        assert result[0]["impactScore"] == 72

    def test_respects_limit(self, repo, mock_table):
        mock_table.query.return_value = {"Items": []}
        repo.list_analyses("user1", limit=5)
        call_kwargs = mock_table.query.call_args[1]
        assert call_kwargs["Limit"] == 5


class TestGetLatestAnalysisLegacyCoercion:
    """Read-side coercion of legacy ``insights: List<String>`` shape.

    Validates Requirement 8.10 / Property 13: ``get_latest_analysis`` returns
    the bilingual map ``{"en": [], "pt-BR": <legacy>}`` for legacy items, never
    mutates the underlying DynamoDB item, and emits a single INFO log line
    flagging the coercion (so we can grep CloudWatch and watch the legacy
    population drain organically over the 7-day TTL).
    """

    def _legacy_item(self, insights):
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        return {
            "PK": "USER#user1",
            "SK": "ANALYSIS#2026-05-05#abc123",
            "analyzedAt": recent_time,
            "TTL": Decimal(str(int(time.time()) + 86400 * 6)),
            "period": {"startDate": "2026-04-28", "endDate": "2026-05-05"},
            "impactScore": Decimal("72"),
            "impactLevel": "high",
            "correlations": [],
            "insights": insights,
        }

    def test_legacy_list_is_coerced_to_bilingual_map(self, repo, mock_table):
        """Legacy ``insights: ["a", "b"]`` becomes ``{"en": [], "pt-BR": ["a", "b"]}``."""
        legacy_list = ["High Productivity: você está usando Kiro com eficiência.", "Boa cadência."]
        mock_table.query.return_value = {"Items": [self._legacy_item(legacy_list)]}

        result = repo.get_latest_analysis(
            "user1", start_date="2026-04-28", end_date="2026-05-05"
        )

        assert result is not None
        assert result["insights"] == {
            "en": [],
            "pt-BR": [
                "High Productivity: você está usando Kiro com eficiência.",
                "Boa cadência.",
            ],
        }

    def test_bilingual_map_is_returned_unchanged(self, repo, mock_table):
        """A modern bilingual map round-trips structurally."""
        bilingual = {
            "en": ["High Productivity: you are leveraging Kiro effectively."],
            "pt-BR": ["Altíssima Produtividade: você está usando Kiro com eficiência."],
        }
        mock_table.query.return_value = {"Items": [self._legacy_item(bilingual)]}

        result = repo.get_latest_analysis(
            "user1", start_date="2026-04-28", end_date="2026-05-05"
        )

        assert result is not None
        assert result["insights"] == bilingual

    def test_missing_insights_become_empty_bilingual_map(self, repo, mock_table):
        """Missing or ``None`` insights collapse to ``{"en": [], "pt-BR": []}``."""
        item_without_field = self._legacy_item(None)
        item_without_field.pop("insights")
        mock_table.query.return_value = {"Items": [item_without_field]}

        result = repo.get_latest_analysis(
            "user1", start_date="2026-04-28", end_date="2026-05-05"
        )

        assert result is not None
        assert result["insights"] == {"en": [], "pt-BR": []}

    def test_coercion_does_not_mutate_underlying_item(self, repo, mock_table):
        """The DynamoDB item returned by ``query`` MUST remain untouched.

        Verified by checking that a follow-up ``query`` (same mocked Items)
        still surfaces the original list shape — i.e., the repository never
        wrote back the coerced map. Also verified directly on the mock's
        Items reference.
        """
        legacy_list = ["a", "b", "c"]
        items_ref = [self._legacy_item(legacy_list)]
        mock_table.query.return_value = {"Items": items_ref}

        first = repo.get_latest_analysis(
            "user1", start_date="2026-04-28", end_date="2026-05-05"
        )
        assert first["insights"] == {"en": [], "pt-BR": ["a", "b", "c"]}

        # The underlying mocked item still has the original list shape.
        assert items_ref[0]["insights"] == ["a", "b", "c"]
        assert isinstance(items_ref[0]["insights"], list)

        # And a follow-up read returns the same coerced shape — proving
        # the function is read-only and produces consistent output.
        second = repo.get_latest_analysis(
            "user1", start_date="2026-04-28", end_date="2026-05-05"
        )
        assert second["insights"] == {"en": [], "pt-BR": ["a", "b", "c"]}

        # And NO put_item / update_item calls happened (read-only path).
        mock_table.put_item.assert_not_called()
        mock_table.update_item.assert_not_called()

    def test_coercion_emits_info_log_on_legacy_read(self, repo, mock_table, capsys):
        """A single INFO log with ``legacyInsightsCoerced=True`` and ``sk`` is emitted."""
        legacy_list = ["legacy insight"]
        mock_table.query.return_value = {"Items": [self._legacy_item(legacy_list)]}

        result = repo.get_latest_analysis(
            "user1", start_date="2026-04-28", end_date="2026-05-05"
        )
        assert result is not None

        captured = capsys.readouterr().out
        coercion_lines = [line for line in captured.splitlines() if "legacyInsightsCoerced" in line]
        assert len(coercion_lines) == 1, f"expected exactly one coercion log, got: {coercion_lines!r}"

        import json as _json
        log_entry = _json.loads(coercion_lines[0])
        assert log_entry["level"] == "INFO"
        assert log_entry["legacyInsightsCoerced"] is True
        assert log_entry["sk"] == "ANALYSIS#2026-05-05#abc123"

    def test_no_coercion_log_on_bilingual_read(self, repo, mock_table, capsys):
        """A modern bilingual map MUST NOT trigger the coercion log."""
        bilingual = {"en": ["x"], "pt-BR": ["y"]}
        mock_table.query.return_value = {"Items": [self._legacy_item(bilingual)]}

        result = repo.get_latest_analysis(
            "user1", start_date="2026-04-28", end_date="2026-05-05"
        )
        assert result is not None

        captured = capsys.readouterr().out
        coercion_lines = [line for line in captured.splitlines() if "legacyInsightsCoerced" in line]
        assert coercion_lines == []
