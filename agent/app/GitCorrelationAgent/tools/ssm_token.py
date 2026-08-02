"""SSM token resolution — fetches a repository-scoped access token.

Provides `fetch_repo_token(repo_id)`, which reads the decrypted token for a
single repository from AWS Systems Manager Parameter Store, addressed by
`repo_id` rather than a full parameter path or the token value itself. This
keeps a manipulated invocation payload from being able to steer the agent
into reading an arbitrary SSM parameter, even though the agent's IAM policy
is already prefix-scoped to `/kiro-cost-analyzer/git-tokens/*`.

Coupling note: `REPO_ID_PATTERN` matches the shape produced by
`_generate_repo_id()` in `backend/handlers/git_repo_handler.py`
(`uuid.uuid4().hex[:8]` — 8 lowercase hex characters). If that generator
ever changes its output shape, this pattern must change with it.

Duplication note: `SSM_TOKEN_PATH_PREFIX` below is an intentional copy of
`git_shared.git_providers.SSM_TOKEN_PATH_PREFIX`. The agent runs in its own
AgentCore container (own `requirements.txt`/`pyproject.toml`, no shared
Lambda layer attached), so it cannot import the `layers/shared` package the
backend and the migrator use (see design DD-4). If the prefix ever changes
in the shared layer, this literal must be updated to match.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

REPO_ID_PATTERN = re.compile(r"^[0-9a-f]{8}$")

SSM_TOKEN_PATH_PREFIX = "/kiro-cost-analyzer/git-tokens"  # noqa: S105 — SSM path prefix, not a secret


def fetch_repo_token(repo_id: str, ssm_client=None) -> str:
    """Fetch the decrypted access token for a repository, by repoId.

    Validates `repo_id` against `REPO_ID_PATTERN` before constructing the
    SSM parameter name, so a manipulated payload field cannot address an
    arbitrary SSM parameter. Coupled to repo_id generation via
    `_generate_repo_id()` (`uuid.uuid4().hex[:8]`) in `git_repo_handler.py`
    — any change to that generator's output shape must update this pattern.

    Args:
        repo_id: Repository-scoped identifier received in the invocation
            payload (expected shape: 8 lowercase hex characters).
        ssm_client: Optional boto3 SSM client, injected for testability.
            A new client is created via `boto3.client("ssm")` when omitted.

    Returns:
        The decrypted token string, or `""` (never raising) on validation
        failure, `ParameterNotFound`, or any other `ClientError`, logging
        the reason in each case.
    """
    if not repo_id or not REPO_ID_PATTERN.match(repo_id):
        logger.warning("Rejected repo_id failing REPO_ID_PATTERN: %r", repo_id)
        return ""

    import boto3
    from botocore.exceptions import ClientError

    client = ssm_client or boto3.client("ssm")
    parameter_name = f"{SSM_TOKEN_PATH_PREFIX}/{repo_id}"

    # This logs the SSM *parameter name* only (a non-secret path — see
    # SSM_TOKEN_PATH_PREFIX's own noqa above). The decrypted token value
    # from `response` below is never passed to any logger call in this
    # module. Semgrep's credential-disclosure rule pattern-matches on the
    # words "token"/"parameter" in the message string, not on what value
    # is actually interpolated.
    logger.info("Fetching Git token from SSM: repo_id=%s parameter=%s", repo_id, parameter_name)  # nosemgrep: python-logger-credential-disclosure

    try:
        response = client.get_parameter(Name=parameter_name, WithDecryption=True)
    except client.exceptions.ParameterNotFound:
        logger.error("SSM GetParameter failed: repo_id=%s parameter=%s reason=ParameterNotFound", repo_id, parameter_name)
        return ""
    except ClientError as exc:
        logger.error(
            "SSM GetParameter failed: repo_id=%s parameter=%s code=%s message=%s",
            repo_id,
            parameter_name,
            exc.response["Error"].get("Code", "Unknown"),
            exc.response["Error"].get("Message", "Unknown"),
        )
        return ""

    logger.info("SSM GetParameter succeeded: repo_id=%s parameter=%s", repo_id, parameter_name)
    return response.get("Parameter", {}).get("Value", "")
