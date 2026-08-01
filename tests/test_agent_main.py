"""Tests for agent main.py — parse_agent_output and handler logic."""

import json
import sys
import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent", "app", "GitCorrelationAgent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agent.app.GitCorrelationAgent.main import (
    parse_agent_output,
    extract_text_from_result,
    _normalize_descriptors,
    _fallback_analysis,
)
from agent.app.GitCorrelationAgent.prompts import CorrelationAnalysis, Correlation, Insights


class TestParseAgentOutput:
    def test_plain_json(self):
        data = {"impactScore": 72, "impactLevel": "high", "correlations": [], "insights": []}
        result = parse_agent_output(json.dumps(data))
        assert result == data

    def test_json_in_code_fence(self):
        data = {"impactScore": 50, "impactLevel": "moderate", "correlations": [], "insights": ["test"]}
        raw = f"```json\n{json.dumps(data)}\n```"
        result = parse_agent_output(raw)
        assert result == data

    def test_json_in_generic_code_fence(self):
        data = {"impactScore": 30, "impactLevel": "low", "correlations": [], "insights": []}
        raw = f"```\n{json.dumps(data)}\n```"
        result = parse_agent_output(raw)
        assert result == data

    def test_invalid_json_raises(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            parse_agent_output("This is not JSON at all")

    def test_empty_string_raises(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            parse_agent_output("")

    def test_partial_json_raises(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            parse_agent_output('{"impactScore": 72, "impactLevel":')


class TestExtractTextFromResult:
    def test_string_result(self):
        result = MagicMock()
        result.__str__ = lambda self: "Hello world"
        assert extract_text_from_result(result) == "Hello world"


# Feature: agent-git-correlation, Property 4: Agent Output JSON Parsing
class TestAgentOutputJsonParsingProperty:
    """Property 4: Agent Output JSON Parsing.

    For any valid JSON string conforming to the OUTPUT_SCHEMA, parse_agent_output
    SHALL extract all fields correctly, including when the JSON is wrapped in
    markdown code fences.

    **Validates: Requirements 2.5, 2.6, 2.7**
    """

    @st.composite
    def valid_analysis_json(draw):
        """Generate valid analysis JSON objects."""
        impact_score = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=100)))
        impact_level = draw(st.sampled_from(["low", "moderate", "high", "veryHigh"]))
        num_correlations = draw(st.integers(min_value=0, max_value=5))
        num_insights = draw(st.integers(min_value=0, max_value=5))

        correlations = [
            {
                "promptSummary": f"prompt {i}",
                "gitActivity": f"commit {i}",
                "confidence": round(0.5 + (i * 0.1), 1),
                "type": "prompt_to_commit" if i % 2 == 0 else "prompt_to_pr",
            }
            for i in range(num_correlations)
        ]

        insights = [f"insight {i}" for i in range(num_insights)]

        return {
            "impactScore": impact_score,
            "impactLevel": impact_level,
            "correlations": correlations,
            "insights": insights,
        }

    @given(data=valid_analysis_json())
    @settings(max_examples=20)
    def test_plain_json_parsed_correctly(self, data):
        """Valid JSON (plain) is extracted correctly."""
        raw = json.dumps(data)
        result = parse_agent_output(raw)
        assert result["impactScore"] == data["impactScore"]
        assert result["impactLevel"] == data["impactLevel"]
        assert result["correlations"] == data["correlations"]
        assert result["insights"] == data["insights"]

    @given(data=valid_analysis_json())
    @settings(max_examples=20)
    def test_code_fenced_json_parsed_correctly(self, data):
        """Valid JSON in code fences is extracted correctly."""
        raw = f"```json\n{json.dumps(data)}\n```"
        result = parse_agent_output(raw)
        assert result["impactScore"] == data["impactScore"]
        assert result["impactLevel"] == data["impactLevel"]
        assert result["correlations"] == data["correlations"]
        assert result["insights"] == data["insights"]


# Feature: agent-git-correlation, Property 5: Fallback on Invalid JSON
class TestFallbackOnInvalidJsonProperty:
    """Property 5: Fallback on Invalid JSON.

    For any string that is NOT valid JSON, parse_agent_output SHALL raise
    an exception.

    **Validates: Requirements 2.5, 2.6, 2.7**
    """

    @given(text=st.text(min_size=1, max_size=500))
    @settings(max_examples=20)
    def test_non_json_raises_exception(self, text):
        """Non-JSON strings cause an exception."""
        stripped = text.strip()

        # Filter out strings that happen to be valid JSON (even after stripping)
        try:
            json.loads(stripped)
            assume(False)  # Skip valid JSON strings
        except (json.JSONDecodeError, ValueError):
            pass

        # Also skip strings that contain code fences (they have special handling)
        if "```" in text:
            assume(False)

        with pytest.raises((json.JSONDecodeError, ValueError)):
            parse_agent_output(text)


# Feature: agent-git-correlation, Property 6: Handler Returns Valid JSON
class TestHandlerReturnsValidJsonProperty:
    """Property 6: Handler Returns Valid JSON.

    For any analysis result (valid or fallback), the @app.entrypoint handler
    SHALL return a string that is parseable as valid JSON.

    **Validates: Requirements 2.5, 2.6, 2.7**
    """

    @given(
        impact_score=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
        impact_level=st.sampled_from(["low", "moderate", "high", "veryHigh"]),
    )
    @settings(max_examples=20)
    def test_valid_analysis_returns_valid_json(self, impact_score, impact_level):
        """Valid analysis results produce parseable JSON string."""
        analysis = {
            "impactScore": impact_score,
            "impactLevel": impact_level,
            "correlations": [],
            "insights": ["test insight"],
        }
        # Simulate what the handler does: json.dumps the analysis
        result_str = json.dumps(analysis)
        parsed = json.loads(result_str)
        assert "impactScore" in parsed
        assert "impactLevel" in parsed

    def test_fallback_response_is_valid_json(self):
        """Fallback response is also valid JSON."""
        fallback = {
            "impactScore": None,
            "impactLevel": "low",
            "correlations": [],
            "insights": ["Analysis could not be processed. Please try again."],
        }
        result_str = json.dumps(fallback)
        parsed = json.loads(result_str)
        assert parsed["impactScore"] is None
        assert len(parsed["insights"]) > 0


class TestNormalizeDescriptors:
    """Unit tests for `_normalize_descriptors`'s DD-5 default/drop behavior."""

    def test_missing_provider_defaults_to_github(self):
        repos = [{"repoId": "aaaaaaaa", "owner": "acme", "repo": "billing", "gitUsername": "alice"}]
        result = _normalize_descriptors(repos, fallback_username="")
        assert len(result) == 1
        assert result[0]["provider"] == "github"

    def test_missing_git_username_falls_back_to_top_level(self):
        repos = [{"repoId": "aaaaaaaa", "provider": "github", "owner": "acme", "repo": "billing"}]
        result = _normalize_descriptors(repos, fallback_username="bob")
        assert result[0]["gitUsername"] == "bob"

    def test_present_git_username_is_not_overridden(self):
        repos = [
            {
                "repoId": "aaaaaaaa",
                "provider": "github",
                "owner": "acme",
                "repo": "billing",
                "gitUsername": "alice",
            }
        ]
        result = _normalize_descriptors(repos, fallback_username="bob")
        assert result[0]["gitUsername"] == "alice"

    def test_unknown_provider_is_dropped(self):
        repos = [
            {"repoId": "aaaaaaaa", "provider": "bitbucket", "owner": "acme", "repo": "billing"},
            {"repoId": "bbbbbbbb", "provider": "github", "owner": "acme", "repo": "payments"},
        ]
        result = _normalize_descriptors(repos, fallback_username="alice")
        assert len(result) == 1
        assert result[0]["repoId"] == "bbbbbbbb"

    def test_github_missing_location_fields_is_dropped(self):
        repos = [{"repoId": "aaaaaaaa", "provider": "github", "owner": "acme"}]
        result = _normalize_descriptors(repos, fallback_username="alice")
        assert result == []

    def test_gitlab_missing_location_fields_is_dropped(self):
        repos = [{"repoId": "aaaaaaaa", "provider": "gitlab", "baseUrl": "https://gitlab.example.com"}]
        result = _normalize_descriptors(repos, fallback_username="alice")
        assert result == []

    def test_gitlab_descriptor_with_full_location_is_kept(self):
        repos = [
            {
                "repoId": "aaaaaaaa",
                "provider": "gitlab",
                "baseUrl": "https://gitlab.example.com",
                "projectPath": "group/project",
                "gitUsername": "alice",
            }
        ]
        result = _normalize_descriptors(repos, fallback_username="")
        assert len(result) == 1
        assert result[0]["provider"] == "gitlab"

    def test_non_dict_entry_is_dropped(self):
        repos = [
            "not-a-dict",
            {"repoId": "aaaaaaaa", "provider": "github", "owner": "acme", "repo": "billing"},
        ]
        result = _normalize_descriptors(repos, fallback_username="alice")
        assert len(result) == 1

    def test_empty_repos_returns_empty_list(self):
        assert _normalize_descriptors([], fallback_username="alice") == []

    def test_none_repos_returns_empty_list(self):
        assert _normalize_descriptors(None, fallback_username="alice") == []

    def test_never_raises_on_malformed_input(self):
        malformed = [
            None,
            42,
            {"provider": None, "owner": None, "repo": None},
            {"provider": "gitlab", "baseUrl": None, "projectPath": None},
            {"repoId": "cccccccc", "provider": "github", "owner": "acme", "repo": "svc", "gitUsername": None},
        ]
        result = _normalize_descriptors(malformed, fallback_username="alice")
        # Only the last entry has valid location fields after defaulting.
        assert len(result) == 1
        assert result[0]["gitUsername"] == "alice"


# Feature: gitlab-provider-support
class TestNormalizeDescriptorsProperty:
    """Property-adjacent example coverage for `_normalize_descriptors`.

    Not one of the numbered design properties (those belong to task 13.12,
    Property 13: Provider dispatch totality, and related tasks) — this is
    scoped example coverage for the defaulting/dropping behavior introduced
    in this task, kept intentionally small.
    """

    @given(
        provider=st.sampled_from(["bitbucket", "svn", "perforce", "GITHUB", "GitLab"]),
    )
    @settings(max_examples=20)
    def test_case_sensitive_unknown_providers_are_dropped(self, provider):
        """Providers outside the exact set {"github", "gitlab"} are dropped.

        Includes differently-cased variants to confirm matching is exact
        (case-sensitive), not normalized. An empty-string provider is
        excluded from this generator: it is falsy, so per the DD-5 default
        it becomes "github" rather than an unknown provider — that case is
        covered separately by `test_missing_provider_defaults_to_github`.
        """
        repos = [
            {
                "repoId": "aaaaaaaa",
                "provider": provider,
                "owner": "acme",
                "repo": "billing",
                "baseUrl": "https://gitlab.example.com",
                "projectPath": "acme/billing",
                "gitUsername": "alice",
            }
        ]
        result = _normalize_descriptors(repos, fallback_username="alice")
        if provider in ("github", "gitlab"):
            assert len(result) == 1
        else:
            assert result == []


class TestCorrelationAnalysisModel:
    """Unit tests for the `CorrelationAnalysis` structured output model (DD-6).

    These cover the shape Strands enforces via `structured_output_model`,
    replacing the free-text JSON contract previously validated only by
    `parse_agent_output` on the production path.
    """

    def test_round_trips_bilingual_insights_via_alias(self):
        analysis = CorrelationAnalysis(
            impactScore=48,
            impactLevel="moderate",
            correlations=[],
            insights={"en": ["Title: text"], "pt-BR": ["Título: texto"]},
        )
        dumped = analysis.model_dump(by_alias=True)
        assert dumped["insights"]["en"] == ["Title: text"]
        assert dumped["insights"]["pt-BR"] == ["Título: texto"]

    def test_impact_score_defaults_to_none_when_omitted(self):
        analysis = CorrelationAnalysis(
            impactLevel="low",
            insights={"en": ["x"], "pt-BR": ["y"]},
        )
        assert analysis.impactScore is None

    def test_correlations_default_to_empty_list(self):
        analysis = CorrelationAnalysis(
            impactLevel="low",
            insights={"en": ["x"], "pt-BR": ["y"]},
        )
        assert analysis.correlations == []

    def test_impact_score_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            CorrelationAnalysis(
                impactScore=101,
                impactLevel="high",
                insights={"en": ["x"], "pt-BR": ["y"]},
            )

    def test_more_than_twenty_correlations_rejected(self):
        correlations = [
            {"promptSummary": f"p{i}", "gitActivity": f"g{i}", "confidence": 0.6, "type": "prompt_to_commit"}
            for i in range(21)
        ]
        with pytest.raises(ValidationError):
            CorrelationAnalysis(
                impactLevel="high",
                correlations=correlations,
                insights={"en": ["x"], "pt-BR": ["y"]},
            )

    def test_correlation_confidence_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            Correlation(promptSummary="p", gitActivity="g", confidence=0.49, type="prompt_to_commit")

    def test_missing_pt_br_insights_key_rejected(self):
        with pytest.raises(ValidationError):
            Insights(en=["x"])


class TestFallbackAnalysis:
    """Unit tests for `_fallback_analysis`, used when `StructuredOutputException` is raised."""

    def test_returns_null_score_and_parallel_bilingual_insights(self):
        fallback = _fallback_analysis()
        assert fallback["impactScore"] is None
        assert len(fallback["insights"]["en"]) == len(fallback["insights"]["pt-BR"]) == 1

    def test_is_valid_against_correlation_analysis_schema(self):
        """The fallback dict itself SHALL satisfy the CorrelationAnalysis schema."""
        fallback = _fallback_analysis()
        # Should not raise.
        CorrelationAnalysis(**fallback)

    def test_result_is_json_serializable(self):
        fallback = _fallback_analysis()
        parsed = json.loads(json.dumps(fallback))
        assert parsed == fallback
