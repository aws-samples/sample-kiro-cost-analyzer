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


@app.entrypoint
def handler(payload: dict) -> str:
    """AgentCore runtime entrypoint — receives the invocation payload.

    Extracts parameters from payload, builds tools with runtime values,
    creates the agent, and lets it autonomously orchestrate data fetching
    and analysis.

    Args:
        payload: Dict with userId, startDate, endDate, gitUsername, repos, token.

    Returns:
        JSON string with the analysis result.
    """
    # Lazy imports to keep initialization under 30s
    from strands import Agent
    from strands.models.bedrock import BedrockModel
    from prompts import SYSTEM_PROMPT, build_user_prompt
    from tools import build_kiro_tool, build_github_tool

    user_id = payload.get("userId", "")
    start_date = payload.get("startDate", "")
    end_date = payload.get("endDate", "")
    git_username = payload.get("gitUsername", "")
    repos = payload.get("repos", [])

    # Fetch token from SSM at runtime instead of receiving it in the payload
    # — avoids exposing secrets in CloudWatch Logs and Lambda event payloads.
    token = _fetch_token_from_ssm()

    # Build tools with runtime values via factory pattern
    table_name = os.environ.get("ANALYTICS_TABLE", "kiro-cost-analyzer-analytics")
    kiro_tool = build_kiro_tool(table_name)
    github_tool = build_github_tool(token)

    # Create agent with Amazon Bedrock model
    model = BedrockModel(
        model_id="global.anthropic.claude-sonnet-4-6",
        region_name="sa-east-1",
    )

    agent = Agent(
        model=model,
        tools=[kiro_tool, github_tool],
        system_prompt=SYSTEM_PROMPT,
    )

    # Build user prompt describing the analysis task
    user_prompt = build_user_prompt(user_id, start_date, end_date, git_username, repos)

    logger.info("Invoking agent for user=%s period=%s..%s", user_id, start_date, end_date)
    result = agent(user_prompt)

    try:
        analysis = parse_agent_output(extract_text_from_result(result))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to parse agent output: %s", exc)
        analysis = {
            "impactScore": None,
            "impactLevel": "low",
            "correlations": [],
            "insights": {
                "en": ["Analysis could not be processed. Please try again."],
                "pt-BR": ["Não foi possível processar a análise. Tente novamente."],
            },
        }

    return json.dumps(analysis)


def _fetch_token_from_ssm() -> str:
    """Fetch the GitHub access token from AWS Systems Manager Parameter Store.

    Reads the most recently modified SecureString parameter under
    /kiro-cost-analyzer/git-tokens/ and returns its decrypted value.

    Returns:
        The token string, or empty string if not found.
    """
    import boto3
    from botocore.exceptions import ClientError

    ssm_client = boto3.client("ssm", region_name="sa-east-1")

    try:
        response = ssm_client.get_parameters_by_path(
            Path="/kiro-cost-analyzer/git-tokens/",
            WithDecryption=True,
            MaxResults=10,
        )
        params = response.get("Parameters", [])
        if not params:
            logger.warning("No Git tokens found in SSM")
            return ""

        # Return the most recently modified token
        params.sort(key=lambda p: p.get("LastModifiedDate", ""), reverse=True)
        return params[0].get("Value", "")

    except ClientError as exc:
        logger.error(
            "Failed to fetch Git token from SSM: %s (code=%s)",
            exc.response["Error"].get("Message", "Unknown"),
            exc.response["Error"].get("Code", "Unknown"),
        )
        return ""


if __name__ == "__main__":
    app.run()
