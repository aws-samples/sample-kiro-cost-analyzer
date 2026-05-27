"""Prompt Categorizer — classifies prompts into predefined categories using Amazon Bedrock.

Isolated module that invokes Amazon Bedrock (Amazon Nova Lite) via cross-region inference
to classify each prompt into one of 14 predefined categories.  The few-shot
examples are loaded dynamically from S3 (single source of truth) and injected
into the system prompt at initialisation time.

Designed for reuse and independent testing with no ETL pipeline dependencies.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

import boto3

try:
    from shared.categories import CATEGORY_CLASSIFICATION_ERROR, CATEGORY_EMPTY
except ImportError:
    # Fallback for local execution outside the Lambda layer
    from layers.shared.shared.categories import (
        CATEGORY_CLASSIFICATION_ERROR,
        CATEGORY_EMPTY,
    )

logger = logging.getLogger(__name__)

VALID_CATEGORIES = [
    "Code Generation",
    "Debugging",
    "Refactoring",
    "Documentation",
    "Testing",
    "Code Review",
    "Architecture/Design",
    "DevOps/Infrastructure",
    "Data Analysis",
    "Production Troubleshooting",
    "Feedback/Critique",
    "Planning/Discussion",
    "General Q&A",
    "Other",
]

_CATEGORIES_SET = set(VALID_CATEGORIES)

MAX_PROMPT_LENGTH = 5000

_FEW_SHOT_S3_KEY = "config/few-shot-examples.json"

# ---------------------------------------------------------------------------
# Base system prompt — category definitions + classification rules.
# NO hardcoded examples.  Examples are loaded from S3 at runtime and
# appended by ``build_system_prompt_with_examples``.
# ---------------------------------------------------------------------------

BASE_SYSTEM_PROMPT = f"""You are a prompt classifier for an AI coding assistant (Kiro IDE). Given a user prompt, classify it into exactly ONE of these categories:

{chr(10).join(f'- {c}' for c in VALID_CATEGORIES)}

Other:
- Use only when the prompt truly doesn't fit any category above.
- Very short prompts with no technical context that are just acknowledgments like "ok", "beleza" → Planning/Discussion, NOT Other.
- Single words or names that are just calling attention like "kiro?", "kirrro" → Other is acceptable.

Rules:
- Respond with ONLY the category name, nothing else.
- Prefer a specific category over "Other" — use "Other" as last resort.
- Prompts in Portuguese are common. Classify based on intent regardless of language.
- The prompt may be wrapped in Kiro IDE context markers (--- CONTEXT ENTRY BEGIN/END ---, --- USER MESSAGE BEGIN/END ---). Focus ONLY on the user message content for classification.
- Short conversational prompts about planning, agreement, or next steps → "Planning/Discussion".
- Complaints, dissatisfaction, or requests to fix visual/UX issues → "Feedback/Critique".
- Short frustrated messages or dismissals → "Feedback/Critique".
- Questions suggesting alternative technical approaches → "Architecture/Design".
- Requests to deploy, commit, push, or update infrastructure → "DevOps/Infrastructure".
- Requests to investigate errors, check logs, or fix broken things → "Production Troubleshooting" if about production, "Debugging" if about code.
- "General Q&A" is ONLY for genuine questions about concepts or technology. Do NOT use it for short conversational messages."""


class PromptCategorizer:
    """Classifies prompts into predefined categories using Amazon Bedrock.

    At initialisation the classifier loads few-shot examples from S3
    (``config/few-shot-examples.json``) and builds the full system prompt
    by combining the base template with the loaded examples.  If the S3
    file is missing or unreadable the classifier operates with the base
    template only (no examples).

    When a guardrail is configured (via guardrail_id and guardrail_version),
    the classifier applies it to every Bedrock call. If the guardrail
    intervenes, the prompt is categorized as "Blocked by Guardrail".

    Attributes:
        model_id: Amazon Bedrock model ID (e.g. "us.amazon.nova-lite-v1:0").
        region: Amazon Bedrock region (e.g. "us-east-1").
    """

    def __init__(
        self,
        model_id: str,
        region: str,
        bedrock_client=None,
        s3_client=None,
        data_bucket: str = "",
        guardrail_id: str = "",
        guardrail_version: str = "",
    ):
        """Initialize with model ID, Amazon Bedrock region, and optional S3 config.

        Args:
            model_id: ID of the Amazon Bedrock model (e.g. "us.amazon.nova-lite-v1:0").
            region: Amazon Bedrock region (e.g. "us-east-1").
            bedrock_client: Optional boto3 bedrock-runtime client (for testing).
            s3_client: Optional boto3 S3 client (for testing).
            data_bucket: Name of the S3 bucket containing the few-shot
                examples file.  When empty the classifier operates with
                the base template only.
            guardrail_id: Optional Bedrock Guardrail ID to apply on each call.
            guardrail_version: Optional Guardrail version (numeric or "DRAFT").
        """
        self.model_id = model_id
        self.region = region
        self._client = bedrock_client or boto3.client(
            "bedrock-runtime", region_name=region
        )
        self._s3 = s3_client
        self._data_bucket = data_bucket
        self._guardrail_id = guardrail_id
        self._guardrail_version = guardrail_version
        self._full_system_prompt = self._build_system_prompt()

    # ------------------------------------------------------------------
    # S3 example loading
    # ------------------------------------------------------------------

    def _load_examples_from_s3(self) -> list[dict]:
        """Load few-shot examples from S3.

        The S3 file at ``config/few-shot-examples.json`` is the single
        source of truth — there are no hardcoded examples in this module.
        If the file does not exist or cannot be read, logs a warning and
        returns ``[]``, which means the classifier operates with the base
        prompt only (category definitions and rules, but no examples).

        Returns:
            List of example dicts, each with at least ``category`` and
            ``example`` keys.  Returns ``[]`` on any error.
        """
        if not self._data_bucket:
            logger.warning(
                "No data_bucket configured — operating without few-shot examples"
            )
            return []

        s3 = self._s3 or boto3.client("s3")

        try:
            response = s3.get_object(
                Bucket=self._data_bucket, Key=_FEW_SHOT_S3_KEY
            )
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except Exception as exc:
            error_code = (
                getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            )
            if error_code == "NoSuchKey":
                logger.warning(
                    "Few-shot examples file not found at s3://%s/%s "
                    "— operating without examples",
                    self._data_bucket,
                    _FEW_SHOT_S3_KEY,
                )
            else:
                logger.error(
                    "Failed to load few-shot examples from s3://%s/%s: %s",
                    self._data_bucket,
                    _FEW_SHOT_S3_KEY,
                    exc,
                )
            return []

    # ------------------------------------------------------------------
    # System prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the full system prompt from base template + S3 examples.

        Loads examples via ``_load_examples_from_s3`` and delegates to
        the pure static method ``build_system_prompt_with_examples``.

        Returns:
            Complete system prompt string ready for Amazon Bedrock.
        """
        examples = self._load_examples_from_s3()
        return self.build_system_prompt_with_examples(examples)

    @staticmethod
    def build_system_prompt_with_examples(examples: list[dict]) -> str:
        """Construct the full system prompt from the base template and examples.

        This is a pure static method with no I/O dependencies, making it
        easy to test in isolation.

        The examples are grouped by category and formatted as a section
        appended after the base template.  If ``examples`` is empty the
        base template is returned as-is.

        Args:
            examples: List of example dicts.  Each dict must have at
                least ``category`` (str) and ``example`` (str) keys.

        Returns:
            Complete system prompt string.
        """
        if not examples:
            return BASE_SYSTEM_PROMPT

        # Group examples by category
        by_category: dict[str, list[str]] = defaultdict(list)
        for ex in examples:
            category = ex.get("category", "")
            example_text = ex.get("example", "")
            if category and example_text:
                by_category[category].append(example_text)

        if not by_category:
            return BASE_SYSTEM_PROMPT

        # Build the examples section
        lines: list[str] = ["", "Here are examples for each category:", ""]
        for cat in VALID_CATEGORIES:
            cat_examples = by_category.get(cat, [])
            if cat_examples:
                lines.append(f"{cat}:")
                for ex_text in cat_examples:
                    lines.append(f'- "{ex_text}"')
                lines.append("")

        examples_section = "\n".join(lines)
        return BASE_SYSTEM_PROMPT + examples_section

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def categorize(self, prompt_text: str) -> str:
        """Classify a prompt into one of the predefined categories.

        Args:
            prompt_text: The prompt content to classify.

        Returns:
            One of the 14 valid categories, "Other" on error/invalid response,
            "Empty" if the prompt is empty/whitespace-only, or
            "Blocked by Guardrail" if the guardrail intervenes.
        """
        if not prompt_text or not prompt_text.strip():
            return CATEGORY_EMPTY

        truncated = prompt_text[:MAX_PROMPT_LENGTH]

        try:
            kwargs = {
                "modelId": self.model_id,
                "system": [{"text": self._full_system_prompt}],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"text": f"Classify this prompt:\n\n{truncated}"}
                        ],
                    }
                ],
                "inferenceConfig": {
                    "maxTokens": 20,
                    "temperature": 0.0,
                },
            }

            # Apply guardrail if configured
            if self._guardrail_id and self._guardrail_version:
                kwargs["guardrailConfig"] = {
                    "guardrailIdentifier": self._guardrail_id,
                    "guardrailVersion": self._guardrail_version,
                    "trace": "disabled",
                }

            response = self._client.converse(**kwargs)

            # Check if guardrail intervened
            stop_reason = response.get("stopReason", "")
            if stop_reason == "guardrail_intervened":
                logger.warning(
                    "Guardrail intervened for prompt categorization"
                )
                return "Blocked by Guardrail"

            output = (
                response["output"]["message"]["content"][0]["text"].strip()
            )

            if output in _CATEGORIES_SET:
                return output

            logger.warning(
                "Amazon Bedrock returned invalid category: %s", output
            )
            return "Other"

        except Exception:
            logger.exception("Error calling Amazon Bedrock for prompt categorization")
            return CATEGORY_CLASSIFICATION_ERROR
