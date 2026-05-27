"""Tests for etl.prompt_parser module."""

import gzip
import json

import pytest

from etl.prompt_parser import RawPromptRecord, parse_prompt_file


def _make_gzipped_json(data: dict) -> bytes:
    """Helper — compress a dict as gzipped JSON bytes."""
    return gzip.compress(json.dumps(data).encode("utf-8"))


def _sample_record(**overrides) -> dict:
    """Return a single prompt record dict with sensible defaults."""
    record = {
        "generateAssistantResponseEventRequest": {
            "prompt": "Hello?",
            "userId": "d-94671e1709.53ecfaaa-80a1-7073-9432-e0d2acdbd172",
            "modelId": "claude-opus-4.6",
            "chatTriggerType": "MANUAL",
            "timeStamp": "2026-04-10T14:18:03.103Z",
            "customizationArn": None,
        },
        "generateAssistantResponseEventResponse": {
            "assistantResponse": "Hi there!",
            "requestId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "messageMetadata": {
                "conversationId": None,
                "utteranceId": None,
            },
            "followupPrompts": "",
            "codeReferenceEvents": [],
            "supplementaryWebLinksEvent": [],
        },
    }
    record.update(overrides)
    return record


class TestParsePromptFile:
    """Tests for parse_prompt_file."""

    def test_single_record(self):
        payload = _make_gzipped_json({"records": [_sample_record()]})
        result = parse_prompt_file(payload)

        assert len(result) == 1
        rec = result[0]
        assert isinstance(rec, RawPromptRecord)
        assert rec.prompt == "Hello?"
        assert rec.response == "Hi there!"
        assert rec.userId == "d-94671e1709.53ecfaaa-80a1-7073-9432-e0d2acdbd172"
        assert rec.modelId == "claude-opus-4.6"
        assert rec.triggerType == "MANUAL"
        assert rec.timestamp == "2026-04-10T14:18:03.103Z"
        assert rec.customizationArn is None
        assert rec.requestId == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert rec.conversationId is None
        assert rec.utteranceId is None
        assert rec.followupPrompts == ""
        assert rec.codeReferenceEvents == []
        assert rec.supplementaryWebLinksEvent == []

    def test_multiple_records(self):
        r1 = _sample_record()
        r2 = _sample_record()
        r2["generateAssistantResponseEventRequest"]["prompt"] = "Second prompt"
        r2["generateAssistantResponseEventResponse"]["requestId"] = "second-id"

        payload = _make_gzipped_json({"records": [r1, r2]})
        result = parse_prompt_file(payload)

        assert len(result) == 2
        assert result[0].prompt == "Hello?"
        assert result[1].prompt == "Second prompt"
        assert result[1].requestId == "second-id"

    def test_empty_records_returns_empty_list(self):
        payload = _make_gzipped_json({"records": []})
        result = parse_prompt_file(payload)
        assert result == []

    def test_missing_records_key_returns_empty_list(self):
        payload = _make_gzipped_json({"other": "data"})
        result = parse_prompt_file(payload)
        assert result == []

    def test_invalid_gzip_raises(self):
        with pytest.raises(ValueError, match="Failed to decompress gzip"):
            parse_prompt_file(b"not-gzip-data")

    def test_invalid_json_raises(self):
        bad_json = gzip.compress(b"not json {{{")
        with pytest.raises(ValueError, match="Failed to parse JSON"):
            parse_prompt_file(bad_json)

    def test_field_mapping_from_nested_keys(self):
        """Verify chatTriggerType → triggerType and timeStamp → timestamp."""
        rec = _sample_record()
        rec["generateAssistantResponseEventRequest"]["chatTriggerType"] = "AUTO"
        rec["generateAssistantResponseEventRequest"]["timeStamp"] = "2025-01-01T00:00:00Z"

        payload = _make_gzipped_json({"records": [rec]})
        result = parse_prompt_file(payload)

        assert result[0].triggerType == "AUTO"
        assert result[0].timestamp == "2025-01-01T00:00:00Z"
