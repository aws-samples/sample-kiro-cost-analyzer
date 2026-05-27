"""Tests for etl.processors.prompt_processor module."""

import gzip
import json

import pytest

from etl.processors.prompt_processor import process_prompts


def _make_gzipped_json(data: dict) -> bytes:
    """Helper — compress a dict as gzipped JSON bytes."""
    return gzip.compress(json.dumps(data).encode("utf-8"))


def _sample_record(**overrides) -> dict:
    """Return a single prompt record dict with sensible defaults."""
    record = {
        "generateAssistantResponseEventRequest": {
            "prompt": "Hello?",
            "userId": "d-94671e1709.53ecfaaa-80a1-7073-9432-e0d2acdbd172",
            "modelId": "anthropic.claude-sonnet-4-20250514-v1:0",
            "chatTriggerType": "CHAT",
            "timeStamp": "2025-01-15T14:30:25.123Z",
            "customizationArn": None,
        },
        "generateAssistantResponseEventResponse": {
            "assistantResponse": "Hi there!",
            "requestId": "req-abc-123",
            "messageMetadata": {
                "conversationId": "conv-xyz",
                "utteranceId": "utt-456",
            },
            "followupPrompts": "",
            "codeReferenceEvents": [],
            "supplementaryWebLinksEvent": [],
        },
    }
    record.update(overrides)
    return record


_PATH_META = {"region": "us-east-1", "accountId": "673826570926"}
_NAME_CACHE = {
    "53ecfaaa-80a1-7073-9432-e0d2acdbd172": ("João Silva", "joao.silva"),
}


class TestProcessPrompts:
    """Tests for process_prompts."""

    def test_single_record_returns_dynamo_dict(self):
        payload = _make_gzipped_json({"records": [_sample_record()]})
        result = process_prompts(payload, _PATH_META, _NAME_CACHE)

        assert len(result) == 1
        rec = result[0]
        assert rec["userId"] == "53ecfaaa-80a1-7073-9432-e0d2acdbd172"
        assert rec["originalUserId"] == "d-94671e1709.53ecfaaa-80a1-7073-9432-e0d2acdbd172"
        assert rec["timestamp"] == "2025-01-15T14:30:25.123Z"
        assert rec["requestId"] == "req-abc-123"
        assert rec["modelId"] == "anthropic.claude-sonnet-4-20250514-v1:0"
        assert rec["triggerType"] == "CHAT"
        assert rec["promptLength"] == len("Hello?")
        assert rec["responseLength"] == len("Hi there!")
        assert rec["displayName"] == "João Silva"
        assert rec["userName"] == "joao.silva"
        assert rec["region"] == "us-east-1"
        assert rec["accountId"] == "673826570926"
        assert rec["conversationId"] == "conv-xyz"
        assert rec["utteranceId"] == "utt-456"
        assert rec["date"] == "2025-01-15"
        assert rec["hour"] == "14"
        assert rec["prompt"] == "Hello?"
        assert rec["response"] == "Hi there!"

    def test_empty_records_returns_empty_list(self):
        payload = _make_gzipped_json({"records": []})
        assert process_prompts(payload, _PATH_META, _NAME_CACHE) == []

    def test_missing_records_key_returns_empty_list(self):
        payload = _make_gzipped_json({"other": "data"})
        assert process_prompts(payload, _PATH_META, {}) == []

    def test_uuid_extraction_from_directory_prefix(self):
        payload = _make_gzipped_json({"records": [_sample_record()]})
        result = process_prompts(payload, _PATH_META, _NAME_CACHE)
        assert result[0]["userId"] == "53ecfaaa-80a1-7073-9432-e0d2acdbd172"

    def test_name_cache_miss_returns_empty_names(self):
        payload = _make_gzipped_json({"records": [_sample_record()]})
        result = process_prompts(payload, _PATH_META, {})
        assert result[0]["displayName"] == ""
        assert result[0]["userName"] == ""

    def test_multiple_records(self):
        r1 = _sample_record()
        r2 = _sample_record()
        r2["generateAssistantResponseEventRequest"]["prompt"] = "Second"
        r2["generateAssistantResponseEventResponse"]["requestId"] = "req-def-456"

        payload = _make_gzipped_json({"records": [r1, r2]})
        result = process_prompts(payload, _PATH_META, _NAME_CACHE)

        assert len(result) == 2
        assert result[0]["prompt"] == "Hello?"
        assert result[1]["prompt"] == "Second"
        assert result[1]["requestId"] == "req-def-456"

    def test_raw_prompt_and_response_preserved(self):
        """Prompt and response text are included for inline/S3 storage decision later."""
        payload = _make_gzipped_json({"records": [_sample_record()]})
        result = process_prompts(payload, _PATH_META, _NAME_CACHE)
        rec = result[0]
        assert "prompt" in rec
        assert "response" in rec
        assert rec["prompt"] == "Hello?"
        assert rec["response"] == "Hi there!"

    def test_path_metadata_propagated(self):
        meta = {"region": "eu-west-1", "accountId": "111222333444"}
        payload = _make_gzipped_json({"records": [_sample_record()]})
        result = process_prompts(payload, meta, _NAME_CACHE)
        assert result[0]["region"] == "eu-west-1"
        assert result[0]["accountId"] == "111222333444"

    def test_invalid_gzip_raises(self):
        with pytest.raises(ValueError, match="Failed to decompress gzip"):
            process_prompts(b"not-gzip", _PATH_META, {})

    def test_customization_arn_none_becomes_empty_string(self):
        payload = _make_gzipped_json({"records": [_sample_record()]})
        result = process_prompts(payload, _PATH_META, _NAME_CACHE)
        assert result[0]["customizationArn"] == ""
