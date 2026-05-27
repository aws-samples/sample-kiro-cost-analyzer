"""AWS Security Token Service (AWS STS) session manager — creates cross-account Amazon S3 clients via AssumeRole."""

from __future__ import annotations

import os
from typing import Any, Optional

import boto3

try:
    from shared.structured_logger import StructuredLogger
except ImportError:
    from utils.logging import StructuredLogger


def _build_session_name() -> str:
    """Build a RoleSessionName that is CloudTrail-traceable.

    Format: ``kiro-etl-{AWS_LAMBDA_FUNCTION_NAME}``. The Lambda name is
    truncated/padded by AWS IAM to the 64-char RoleSessionName limit.

    Returns:
        A role session name string suitable for ``sts:AssumeRole``.
    """
    lambda_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
    return f"kiro-etl-{lambda_name}"


def _assume_role(
    role_arn: str,
    logger: StructuredLogger,
) -> dict[str, str]:
    """Call ``sts:AssumeRole`` and return the Credentials dict.

    On success, emits a structured log entry with ``roleArn`` and
    ``sessionName``. On failure, emits a structured error log with
    ``roleArn``, ``sessionName``, ``errorType`` and ``errorMessage``, plus
    an AccessDenied-specific hint when applicable, then re-raises the
    underlying exception so callers (and Step Functions) can retry.

    Args:
        role_arn: ARN of the IAM role to assume.
        logger: Structured logger used for success and failure events.

    Returns:
        The ``Credentials`` sub-dict from the ``sts:AssumeRole`` response,
        containing ``AccessKeyId``, ``SecretAccessKey`` and ``SessionToken``.

    Raises:
        botocore.exceptions.ClientError: If ``sts:AssumeRole`` fails
            (propagated).
    """
    session_name = _build_session_name()
    try:
        sts = boto3.client("sts")
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            DurationSeconds=3600,
        )
        logger.info(
            "Cross-account role assumed successfully",
            roleArn=role_arn,
            sessionName=session_name,
        )
        return response["Credentials"]
    except Exception as exc:
        error_type = type(exc).__name__
        logger.error(
            "Failed to assume cross-account role",
            roleArn=role_arn,
            sessionName=session_name,
            errorType=error_type,
            errorMessage=str(exc),
        )
        if "AccessDenied" in error_type or "AccessDenied" in str(exc):
            logger.error(
                "Check the trust policy of the target role and the "
                "sts:AssumeRole permissions in the KCA account",
                roleArn=role_arn,
            )
        raise


def get_s3_client(
    role_arn: str,
    correlation_id: str = "",
) -> Optional[Any]:
    """Obtain an S3 client with cross-account credentials via STS AssumeRole.

    Args:
        role_arn: ARN of the IAM role to assume. If empty or None, returns None
                  to indicate single-account mode.
        correlation_id: Optional correlation ID for structured logging.

    Returns:
        A boto3 S3 client with temporary credentials, or None if role_arn is empty.

    Raises:
        botocore.exceptions.ClientError: If AssumeRole fails (propagated).
    """
    logger = StructuredLogger("sts-session-manager", correlation_id)

    if not role_arn:
        return None

    credentials = _assume_role(role_arn, logger)

    return boto3.client(
        "s3",
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )


def get_identity_store_client(
    role_arn: str,
    correlation_id: str = "",
) -> Optional[Any]:
    """Obtain an ``identitystore`` client with cross-account credentials.

    Uses :func:`_assume_role` to fetch temporary credentials via
    ``sts:AssumeRole`` (with ``DurationSeconds=3600`` and the shared
    CloudTrail-traceable session name from :func:`_build_session_name`) and
    builds a boto3 ``identitystore`` client from them. Exceptions raised by
    ``_assume_role`` are propagated so Step Functions retries apply.

    Args:
        role_arn: ARN of the IAM role to assume in the IDC account. If empty
            or ``None``, returns ``None`` so callers fall back to
            single-account mode (default ``boto3.client("identitystore")``).
        correlation_id: Optional correlation ID for structured logging.

    Returns:
        A boto3 ``identitystore`` client built with temporary credentials,
        or ``None`` when ``role_arn`` is empty or ``None``.

    Raises:
        botocore.exceptions.ClientError: If ``sts:AssumeRole`` fails
            (propagated so Step Functions retries apply).
    """
    logger = StructuredLogger("sts-session-manager", correlation_id)

    if not role_arn:
        return None

    credentials = _assume_role(role_arn, logger)

    return boto3.client(
        "identitystore",
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )
