"""ETL configuration — reads parameters from AWS Systems Manager Parameter Store.

Config is read once per warm Lambda container and cached at module scope. This
matters under the Distributed Map ETL: hundreds of concurrent Parse invocations
each reading several SSM parameters can exceed the SSM GetParameter throughput
limit (~40 TPS by default). Caching collapses the per-invocation reads to a
single ``GetParameters`` call per cold start.

Transient SSM failures (throttling) are NOT silently swallowed: a throttled read
of an optional parameter used to fall through to single-account mode, which made
the cross-account S3 client silently become the Lambda's own role and produced
intermittent cross-account AccessDenied at GetObject time. Throttling now
propagates so Step Functions retries with backoff.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import boto3
from botocore.config import Config as BotoConfig

# Adaptive retry mode backs off on ThrottlingException instead of failing fast.
_SSM_CONFIG = BotoConfig(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-scope cache — populated once per warm container.
_cached_config: "EtlConfig | None" = None


def reset_cache() -> None:
    """Clear the per-container config cache.

    Production never calls this (the cache lives for the container's lifetime);
    tests use it to isolate cases.
    """
    global _cached_config  # noqa: PLW0603 - test isolation helper
    _cached_config = None


@dataclass(frozen=True)
class EtlConfig:
    """Configuration for the ETL pipeline."""

    bucket_name: str
    source_prefix: str
    prompts_prefix: str
    identity_store_id: str
    source_bucket_role_arn: str
    identity_store_role_arn: str


def get_config() -> EtlConfig:
    """Read ETL configuration from SSM Parameter Store (cached per container).

    Environment variables hold the SSM parameter *paths* (set by the SAM
    template): ``SSM_BUCKET_NAME`` and ``SSM_SOURCE_PREFIX`` are required;
    ``SSM_PROMPTS_PREFIX``, ``SSM_IDENTITY_STORE_ID``,
    ``SSM_SOURCE_BUCKET_ROLE_ARN`` and ``SSM_IDENTITY_STORE_ROLE_ARN`` are
    optional.

    All configured parameters are fetched in a single ``GetParameters`` call.
    Optional parameters that are *absent* (env var unset, or the parameter does
    not exist — returned under ``InvalidParameters``) resolve to an empty
    string. A stored sentinel value of ``"NONE"`` (written by the template when
    no cross-account role is configured) also resolves to an empty string.
    Transient SSM failures (throttling) raise ``ClientError`` from the batched
    call and propagate, so the caller's retry policy (Step Functions) applies —
    the pipeline must never silently degrade to single-account mode on a
    transient error.

    Returns:
        The cached :class:`EtlConfig` for this container, building it on first
        call.

    Raises:
        botocore.exceptions.ClientError: On transient SSM errors (propagated so
            Step Functions retries).
        KeyError: If a required parameter env var is unset.
    """
    global _cached_config  # noqa: PLW0603 - module-scope cache for Lambda warm-start
    if _cached_config is not None:
        return _cached_config

    ssm = boto3.client("ssm", config=_SSM_CONFIG)

    # Map each config field to its SSM parameter path. Required fields raise
    # KeyError if the env var is unset; optional fields resolve to "" when the
    # env var is unset.
    paths = {
        "bucket_name": os.environ["SSM_BUCKET_NAME"],
        "source_prefix": os.environ["SSM_SOURCE_PREFIX"],
        "prompts_prefix": os.environ.get("SSM_PROMPTS_PREFIX", ""),
        "identity_store_id": os.environ.get("SSM_IDENTITY_STORE_ID", ""),
        "source_bucket_role_arn": os.environ.get("SSM_SOURCE_BUCKET_ROLE_ARN", ""),
        "identity_store_role_arn": os.environ.get("SSM_IDENTITY_STORE_ROLE_ARN", ""),
    }

    # Single batched read for every configured path. GetParameters fetches up to
    # 10 names in one network call, collapsing six per-invocation reads into one
    # and keeping us well under the SSM throughput limit even under the
    # Distributed Map's high concurrency. A throttled or failed read raises
    # ClientError, which propagates so Step Functions retries with backoff — we
    # must never degrade to single-account mode on a transient SSM error.
    names = sorted({p for p in paths.values() if p})
    resp = ssm.get_parameters(Names=names)
    values = {param["Name"]: param["Value"] for param in resp["Parameters"]}

    def resolve(path: str) -> str:
        """Resolve a parameter path to its value.

        Absent path (optional, env var unset) or a parameter missing from the
        response resolves to "". The "NONE" sentinel (written by the template
        when no value is configured) also resolves to "".
        """
        if not path:
            return ""
        raw = values.get(path, "")
        return "" if raw == "NONE" else raw

    _cached_config = EtlConfig(
        bucket_name=resolve(paths["bucket_name"]),
        source_prefix=resolve(paths["source_prefix"]),
        prompts_prefix=resolve(paths["prompts_prefix"]),
        identity_store_id=resolve(paths["identity_store_id"]),
        source_bucket_role_arn=resolve(paths["source_bucket_role_arn"]),
        identity_store_role_arn=resolve(paths["identity_store_role_arn"]),
    )
    return _cached_config
