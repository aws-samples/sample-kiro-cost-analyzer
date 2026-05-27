"""S3 reader for prompt logs — lists and reads .json.gz files."""

from __future__ import annotations

from typing import List

import boto3

PROMPT_SUBPATH = "GenerateAssistantResponse/"


def list_prompt_files(bucket: str, prompts_prefix: str, s3_client=None) -> List[str]:
    """List all ``.json.gz`` files recursively under the prompts prefix.

    Navigates: ``{prompts_prefix}GenerateAssistantResponse/{region}/{year}/{month}/{day}/{hour}/*.json.gz``

    Handles S3 pagination via *ContinuationToken* and filters only
    ``.json.gz`` files.
    """
    s3 = s3_client or boto3.client("s3")
    gz_keys: List[str] = []

    full_prefix = f"{prompts_prefix}{PROMPT_SUBPATH}"
    continuation_token: str | None = None

    while True:
        kwargs: dict = {"Bucket": bucket, "Prefix": full_prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = s3.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            key: str = obj["Key"]
            if key.endswith(".json.gz"):
                gz_keys.append(key)

        if response.get("IsTruncated"):
            continuation_token = response["NextContinuationToken"]
        else:
            break

    return gz_keys


def read_prompt_file(bucket: str, key: str, s3_client=None) -> bytes:
    """Read raw gzipped bytes of a ``.json.gz`` file from S3."""
    s3 = s3_client or boto3.client("s3")
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()
