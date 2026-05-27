"""ETL configuration — reads parameters from AWS Systems Manager Parameter Store."""

import os
from dataclasses import dataclass

import boto3


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
    """Read ETL configuration from SSM Parameter Store.

    Environment variables SSM_BUCKET_NAME and SSM_SOURCE_PREFIX
    hold the SSM parameter paths (set by the SAM template).
    SSM_PROMPTS_PREFIX and SSM_IDENTITY_STORE_ID are optional.
    """
    ssm = boto3.client("ssm")

    bucket_param = os.environ["SSM_BUCKET_NAME"]
    prefix_param = os.environ["SSM_SOURCE_PREFIX"]

    bucket_name = ssm.get_parameter(Name=bucket_param)["Parameter"]["Value"]
    source_prefix = ssm.get_parameter(Name=prefix_param)["Parameter"]["Value"]

    # Read prompts prefix (optional — empty string if not configured)
    prompts_prefix = ""
    prompts_param = os.environ.get("SSM_PROMPTS_PREFIX", "")
    if prompts_param:
        try:
            prompts_prefix = ssm.get_parameter(Name=prompts_param)["Parameter"]["Value"]
        except Exception:
            prompts_prefix = ""

    # Read identity store id (optional — empty string if not configured)
    identity_store_id = ""
    identity_param = os.environ.get("SSM_IDENTITY_STORE_ID", "")
    if identity_param:
        try:
            identity_store_id = ssm.get_parameter(Name=identity_param)["Parameter"]["Value"]
        except Exception:
            identity_store_id = ""

    # Read source bucket role ARN (optional — empty string if not configured)
    source_bucket_role_arn = ""
    role_arn_param = os.environ.get("SSM_SOURCE_BUCKET_ROLE_ARN", "")
    if role_arn_param:
        try:
            raw = ssm.get_parameter(Name=role_arn_param)["Parameter"]["Value"]
            source_bucket_role_arn = "" if raw == "NONE" else raw
        except Exception:
            source_bucket_role_arn = ""

    # Read identity store role ARN (optional — empty string if not configured)
    identity_store_role_arn = ""
    idc_role_arn_param = os.environ.get("SSM_IDENTITY_STORE_ROLE_ARN", "")
    if idc_role_arn_param:
        try:
            raw = ssm.get_parameter(Name=idc_role_arn_param)["Parameter"]["Value"]
            identity_store_role_arn = "" if raw == "NONE" else raw
        except Exception:
            identity_store_role_arn = ""

    return EtlConfig(
        bucket_name=bucket_name,
        source_prefix=source_prefix,
        prompts_prefix=prompts_prefix,
        identity_store_id=identity_store_id,
        source_bucket_role_arn=source_bucket_role_arn,
        identity_store_role_arn=identity_store_role_arn,
    )
