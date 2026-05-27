"""Unit tests for shared/sk_normalizer.py — normalize_sk_value."""

import pytest
from shared.sk_normalizer import normalize_sk_value, MAX_SK_LENGTH


class TestNormalizeSKValue:
    """Tests for the normalize_sk_value transformation pipeline."""

    # --- Design document examples ---

    def test_model_id_with_dots_and_colons(self):
        assert normalize_sk_value("anthropic.claude-sonnet-4-20250514-v1:0") == "anthropic-claude-sonnet-4-20250514-v1-0"

    def test_uppercase_single_word(self):
        assert normalize_sk_value("CHAT") == "chat"

    def test_uppercase_with_underscore(self):
        assert normalize_sk_value("INLINE_CHAT") == "inline-chat"

    def test_mixed_case_with_spaces(self):
        assert normalize_sk_value("Claude Opus 2.6M bla bla") == "claude-opus-2-6m-bla-bla"

    def test_spaces_around(self):
        assert normalize_sk_value("  spaces  around  ") == "spaces-around"

    def test_special_characters(self):
        assert normalize_sk_value("special!@#chars$%^") == "special-chars"

    # --- Edge cases ---

    def test_empty_string(self):
        assert normalize_sk_value("") == ""

    def test_only_spaces(self):
        assert normalize_sk_value("   ") == ""

    def test_only_special_chars(self):
        assert normalize_sk_value("!@#$%^&*()") == ""

    def test_single_alphanumeric(self):
        assert normalize_sk_value("a") == "a"

    def test_already_normalized(self):
        assert normalize_sk_value("already-normalized") == "already-normalized"

    def test_truncation_at_128(self):
        long_input = "a" * 200
        result = normalize_sk_value(long_input)
        assert len(result) == MAX_SK_LENGTH
        assert result == "a" * MAX_SK_LENGTH

    def test_hyphens_not_at_boundaries_after_truncation(self):
        # Build a string that would produce trailing hyphen at position 128
        input_val = "a" * 127 + "!b"
        result = normalize_sk_value(input_val)
        assert not result.startswith("-")
        assert not result.endswith("-")
        assert len(result) <= MAX_SK_LENGTH

    def test_consecutive_special_chars_collapse(self):
        assert normalize_sk_value("a!!!b") == "a-b"

    def test_leading_trailing_special_chars(self):
        assert normalize_sk_value("---hello---") == "hello"

    # --- Canonical map ---

    def test_canonical_map_match(self):
        cmap = {"anthropic.claude-sonnet-4-20250514-v1:0": "claude-sonnet-4"}
        assert normalize_sk_value("anthropic.claude-sonnet-4-20250514-v1:0", canonical_map=cmap) == "claude-sonnet-4"

    def test_canonical_map_no_match(self):
        cmap = {"other-key": "other-value"}
        assert normalize_sk_value("CHAT", canonical_map=cmap) == "chat"

    def test_canonical_map_none(self):
        assert normalize_sk_value("CHAT", canonical_map=None) == "chat"

    def test_canonical_map_empty(self):
        assert normalize_sk_value("CHAT", canonical_map={}) == "chat"

    def test_canonical_value_still_normalized(self):
        cmap = {"RAW": "  CANONICAL VALUE  "}
        result = normalize_sk_value("RAW", canonical_map=cmap)
        assert result == "canonical-value"

    # --- Determinism and idempotence ---

    def test_determinism(self):
        val = "Some Random! Input @#$"
        assert normalize_sk_value(val) == normalize_sk_value(val)

    def test_idempotence(self):
        val = "Some Random! Input @#$"
        once = normalize_sk_value(val)
        twice = normalize_sk_value(once)
        assert once == twice
