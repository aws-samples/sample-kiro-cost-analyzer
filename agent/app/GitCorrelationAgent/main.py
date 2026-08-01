"""GitCorrelationAgent — Entrypoint for the AgentCore runtime.

Orchestrates the correlation analysis between Kiro prompts and Git activity
using Claude Sonnet via Amazon Bedrock. The agent autonomously calls tools to gather
data, then performs semantic analysis.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

# Providers this agent can dispatch to. Kept as a local constant rather than
# importing `git_shared.git_providers.SUPPORTED_PROVIDERS` — the agent runs
# in its own AgentCore container with no shared Lambda layer attached (see
# design DD-4), so it cannot import the `layers/shared` package.
_SUPPORTED_PROVIDERS = frozenset({"github", "gitlab"})

# Location fields each provider's descriptor must carry for the matching
# tool to be callable. Mirrors the shape produced by
# `backend/handlers/agent_correlation_handler.build_repo_descriptors`.
_REQUIRED_LOCATION_FIELDS: dict[str, tuple[str, ...]] = {
    "github": ("owner", "repo"),
    "gitlab": ("baseUrl", "projectPath"),
}


def extract_text_from_result(result: Any) -> str:
    """Extract the text content from a Strands AgentResult."""
    text = str(result)
    if text:
        return text
    msg = result.message
    if isinstance(msg, dict):
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                return block["text"]
    return str(msg)


def parse_agent_output(raw_output: str) -> dict:
    """Extract JSON from the agent's response text.

    Handles plain JSON and JSON wrapped in markdown code fences.

    Args:
        raw_output: Raw text output from the agent.

    Returns:
        Parsed dict from the JSON content.

    Raises:
        json.JSONDecodeError: If no valid JSON can be extracted.
        ValueError: If code fence markers are malformed.
    """
    text = raw_output.strip()

    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    return json.loads(text)


def _normalize_descriptors(repos: list[dict], fallback_username: str) -> list[dict]:
    """Apply the DD-5 backward-compatibility defaults to repository descriptors.

    The backend and the agent deploy independently, so the invocation
    payload is additive (DD-5): an older backend build may send plain
    ``{owner, repo}`` dicts with no ``provider`` tag at all, and any
    descriptor may omit its own ``gitUsername``. This function applies the
    documented defaults and drops anything that still cannot be dispatched
    to a known tool after defaulting, logging a warning for every drop so
    exclusions are never silent.

    Defaults applied, in order:
        1. A descriptor with no ``provider`` (missing, ``None``, or falsy)
           is treated as ``provider="github"``.
        2. A descriptor with no ``gitUsername`` (missing, ``None``, or
           falsy) falls back to ``fallback_username``.

    Drop conditions, each logged via ``logger.warning``:
        - The provider (after defaulting) is not in
          ``{"github", "gitlab"}``.
        - The descriptor is missing a location field its provider
          requires: ``github`` needs both ``owner`` and ``repo``;
          ``gitlab`` needs both ``baseUrl`` and ``projectPath``.

    Never raises on malformed input: entries that are not dicts are dropped
    with a warning, and every field access goes through ``.get()`` rather
    than direct indexing.

    Args:
        repos: Raw ``repos`` list from the invocation payload, as sent by
            either an older or a newer backend build.
        fallback_username: The top-level payload ``gitUsername``, used when
            a descriptor carries no per-repository username of its own.

    Returns:
        The filtered/defaulted list of descriptors. Every returned entry
        has a ``provider`` in ``{"github", "gitlab"}`` and its provider's
        required location fields present.
    """
    normalized: list[dict] = []

    for repo in repos or []:
        if not isinstance(repo, dict):
            logger.warning("Dropping malformed repository descriptor (not an object): %r", repo)
            continue

        descriptor = dict(repo)
        repo_id = descriptor.get("repoId", "<unknown>")

        provider = descriptor.get("provider") or "github"
        descriptor["provider"] = provider

        if not descriptor.get("gitUsername"):
            descriptor["gitUsername"] = fallback_username

        if provider not in _SUPPORTED_PROVIDERS:
            logger.warning(
                "Dropping repository descriptor with unrecognized provider: repoId=%s provider=%r",
                repo_id,
                provider,
            )
            continue

        required_fields = _REQUIRED_LOCATION_FIELDS[provider]
        missing = [field for field in required_fields if not descriptor.get(field)]
        if missing:
            logger.warning(
                "Dropping repository descriptor missing required location fields: "
                "repoId=%s provider=%s missing=%s",
                repo_id,
                provider,
                missing,
            )
            continue

        normalized.append(descriptor)

    return normalized


@app.entrypoint
def handler(payload: dict) -> str:
    """AgentCore runtime entrypoint — receives the invocation payload.

    Extracts parameters from payload, builds tools with runtime values,
    creates the agent, and lets it autonomously orchestrate data fetching
    and analysis.

    Args:
        payload: Dict with userId, startDate, endDate, gitUsername, repos.

    Returns:
        JSON string with the analysis result.
    """
    # Lazy imports to keep initialization under 30s
    from strands import Agent
    from strands.models.bedrock import BedrockModel
    from strands.types.exceptions import StructuredOutputException
    from prompts import SYSTEM_PROMPT, CorrelationAnalysis, build_user_prompt
    from tools import build_kiro_tool, build_github_tool, build_gitlab_tool

    user_id = payload.get("userId", "")
    start_date = payload.get("startDate", "")
    end_date = payload.get("endDate", "")
    git_username = payload.get("gitUsername", "")
    repos = _normalize_descriptors(payload.get("repos", []), git_username)

    # Build tools with runtime values via factory pattern. Both provider
    # tools are registered unconditionally — the prompt decides which one
    # is actually called per repository — and neither factory takes a
    # token anymore: each tool resolves its own token lazily, per call,
    # keyed by the `repo_id` argument the model passes in.
    table_name = os.environ.get("ANALYTICS_TABLE", "kiro-cost-analyzer-analytics")
    kiro_tool = build_kiro_tool(table_name)
    github_tool = build_github_tool()
    gitlab_tool = build_gitlab_tool()

    # Create agent with Amazon Bedrock model
    model = BedrockModel(
        model_id="global.anthropic.claude-sonnet-4-6",
        region_name="sa-east-1",
    )

    agent = Agent(
        model=model,
        tools=[kiro_tool, github_tool, gitlab_tool],
        system_prompt=SYSTEM_PROMPT,
    )

    # Build user prompt describing the analysis task, using the normalized
    # (defaulted/filtered) descriptors rather than the raw payload repos.
    user_prompt = build_user_prompt(user_id, start_date, end_date, git_username, repos)

    logger.info("Invoking agent for user=%s period=%s..%s", user_id, start_date, end_date)

    # `structured_output_model` makes Strands enforce CorrelationAnalysis's shape
    # via a schema-constrained tool call, instead of asking the model to hand-format
    # a JSON blob in free text and then parsing that text ourselves. This removes the
    # malformed-JSON failure mode at the source (see design DD-6) rather than only
    # detecting it after the fact.
    try:
        result = agent(user_prompt, structured_output_model=CorrelationAnalysis)
        analysis = result.structured_output.model_dump(by_alias=True)
    except StructuredOutputException as exc:
        # Only the exception's class name is logged. The exception body
        # (str(exc)) can echo back the model's malformed output, which is
        # ultimately derived from the user's own Kiro prompts and Git
        # activity — never log it, even truncated.
        logger.error("Structured output validation failed: exc_type=%s", type(exc).__name__)
        analysis = _fallback_analysis()

    return json.dumps(analysis)


def _fallback_analysis() -> dict:
    """Build the fallback analysis payload returned when structured output fails.

    Returns:
        A dict shaped like `CorrelationAnalysis`, with a null score and a
        bilingual insight explaining that the analysis could not be produced.
    """
    return {
        "impactScore": None,
        "impactLevel": "low",
        "correlations": [],
        "insights": {
            "en": ["Analysis could not be processed. Please try again."],
            "pt-BR": ["Não foi possível processar a análise. Tente novamente."],
        },
    }


if __name__ == "__main__":
    app.run()
