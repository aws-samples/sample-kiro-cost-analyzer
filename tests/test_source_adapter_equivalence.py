"""Golden-model and registry tests for the ETL source-adapter seam."""

from __future__ import annotations

import csv
import gzip
import io
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from hypothesis import given, strategies as st

from etl.processors.csv_processor import process_csv
from etl.processors.prompt_processor import process_prompts
from etl.sources import AdapterRegistry
from etl.sources.kiro_csv import KiroCsvAdapter
from etl.sources.kiro_prompt_log import KiroPromptLogAdapter


CSV_PREFIX = "activities/AWSLogs/123456789012/KiroLogs/"
PROMPT_PREFIX = "prompts/AWSLogs/123456789012/KiroLogs/"
CSV_KEY = (
    f"{CSV_PREFIX}user_report/us-east-1/2026/09/14/00/"
    "KIRO_IDE_123456789012_user_report_202609140000.csv"
)
PROMPT_KEY = (
    f"{PROMPT_PREFIX}GenerateAssistantResponse/us-east-1/"
    "2026/09/14/00/file.json.gz"
)


def _config():
    return SimpleNamespace(
        source_prefix=CSV_PREFIX,
        prompts_prefix=PROMPT_PREFIX,
    )


def _csv_content(
    user_id: str,
    client_type: str,
    messages: int,
    conversations: int,
    credits: float,
    overage: float,
) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([
        "Date",
        "UserId",
        "Client_Type",
        "Subscription_Tier",
        "ProfileId",
        "Total_Messages",
        "Chat_Conversations",
        "Credits_Used",
        "Overage_Enabled",
        "Overage_Cap",
        "Overage_Credits_Used",
    ])
    writer.writerow([
        "2026-09-14",
        user_id,
        client_type,
        "PRO_PLUS",
        "arn:aws:codewhisperer:us-east-1:123456789012:profile/test",
        messages,
        conversations,
        credits,
        "true",
        10000,
        overage,
    ])
    return stream.getvalue()


@given(
    user_id=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=24,
    ),
    client_type=st.sampled_from(["KIRO_IDE", "KIRO_CLI", "PLUGIN"]),
    messages=st.integers(min_value=0, max_value=100_000),
    conversations=st.integers(min_value=0, max_value=10_000),
    credits=st.floats(min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False),
    overage=st.floats(min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False),
)
def test_kiro_csv_adapter_matches_existing_processor(
    user_id, client_type, messages, conversations, credits, overage
):
    """Adapter composition must remain equal to the pre-seam public processor."""
    content = _csv_content(
        user_id, client_type, messages, conversations, credits, overage
    )
    adapter = KiroCsvAdapter()

    parsed = adapter.parse(content, CSV_KEY, _config())
    actual = adapter.normalize(parsed)

    metadata = {
        "format_type": "new",
        "region": "us-east-1",
        "year": "2026",
        "month": "09",
        "day": "14",
        "account_id": "123456789012",
        "client_type": "KIRO_IDE",
    }
    assert actual == process_csv(content, "new", metadata)


@given(
    prompt=st.text(max_size=256),
    response=st.text(max_size=256),
    request_id=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=24,
    ),
    trigger=st.sampled_from(["CHAT", "INLINE_CHAT", "CODE_WITH_ME"]),
)
def test_kiro_prompt_adapter_matches_existing_processor(
    prompt, response, request_id, trigger
):
    """Adapter composition must remain equal to the pre-seam public processor."""
    raw = {
        "generateAssistantResponseEventRequest": {
            "prompt": prompt,
            "userId": "d-123.53ecfaaa-80a1-7073-9432-e0d2acdbd172",
            "modelId": "anthropic.claude-sonnet-4-20250514-v1:0",
            "chatTriggerType": trigger,
            "timeStamp": "2026-09-14T00:01:02.003Z",
            "customizationArn": None,
        },
        "generateAssistantResponseEventResponse": {
            "assistantResponse": response,
            "requestId": request_id,
            "messageMetadata": {
                "conversationId": "conv-1",
                "utteranceId": "utt-1",
            },
        },
    }
    payload = gzip.compress(json.dumps({"records": [raw]}).encode("utf-8"))
    adapter = KiroPromptLogAdapter()

    parsed = adapter.parse(payload, PROMPT_KEY, _config())
    actual = adapter.normalize(parsed)

    expected = process_prompts(
        payload,
        {"region": "us-east-1", "accountId": "123456789012"},
        {},
    )
    assert actual == expected


@dataclass(frozen=True)
class _FakeAdapter:
    source_type: str
    aliases: tuple[str, ...]
    wire_type: str
    claimed_suffix: str = ".data"
    candidates: tuple[str, ...] = ()
    record_kind: str = "activity"
    count_key: str = "totalFakeFiles"
    requires_content_placement: bool = False
    access_denied_message: str = "denied"

    def claim(self, key, config):
        return key.endswith(self.claimed_suffix)

    def list_files(self, bucket, config, s3_client=None):
        return list(self.candidates)

    def read(self, bucket, key, s3_client=None):
        raise NotImplementedError

    def parse(self, content, key, config):
        raise NotImplementedError

    def normalize(self, parsed):
        raise NotImplementedError


def test_registry_first_claim_wins():
    first = _FakeAdapter("first", ("old-first",), "old-first")
    second = _FakeAdapter("second", ("old-second",), "old-second")
    registry = AdapterRegistry((first, second))

    assert registry.claim("key.data", _config()) is first


def test_registry_resolves_canonical_and_legacy_names():
    csv_adapter = KiroCsvAdapter()
    prompt_adapter = KiroPromptLogAdapter()
    registry = AdapterRegistry((csv_adapter, prompt_adapter))

    assert registry.resolve("csv") is csv_adapter
    assert registry.resolve("kiro_csv") is csv_adapter
    assert registry.resolve("prompt") is prompt_adapter
    assert registry.resolve("kiro_prompt_log") is prompt_adapter


def test_registry_rejects_duplicate_aliases():
    first = _FakeAdapter("first", ("shared",), "first-wire")
    second = _FakeAdapter("second", ("shared",), "second-wire")

    with pytest.raises(ValueError, match="Duplicate source type or alias: shared"):
        AdapterRegistry((first, second))


def test_registry_rejects_duplicate_wire_types():
    first = _FakeAdapter("first", (), "same-wire")
    second = _FakeAdapter("second", (), "same-wire")

    with pytest.raises(ValueError, match="Duplicate wire type: same-wire"):
        AdapterRegistry((first, second))


def test_registry_unknown_type_raises():
    registry = AdapterRegistry((KiroCsvAdapter(),))

    with pytest.raises(ValueError, match="Unknown fileType: parquet"):
        registry.resolve("parquet")


def test_registry_discovery_deduplicates_and_reports_unclaimed_keys():
    first = _FakeAdapter(
        "first",
        (),
        "first-wire",
        candidates=("shared.data", "unclaimed.tmp"),
        count_key="firstCount",
    )
    second = _FakeAdapter(
        "second",
        (),
        "second-wire",
        candidates=("shared.data", "second.data"),
        count_key="secondCount",
    )
    registry = AdapterRegistry((first, second))

    result = registry.discover("bucket", _config())

    assert [(item.key, item.adapter) for item in result.files] == [
        ("shared.data", first),
        ("second.data", first),
    ]
    assert result.counts == {"firstCount": 2, "secondCount": 2}
    assert result.unclaimed_keys == ("unclaimed.tmp",)
