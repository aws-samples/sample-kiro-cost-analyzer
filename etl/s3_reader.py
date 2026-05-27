"""S3 reader — navigates the source bucket and reads CSV files."""

from __future__ import annotations

from typing import List

import boto3

NEW_SUBPATH = "user_report/"


def list_csv_files(bucket: str, prefix: str, s3_client=None) -> List[str]:
    """List CSV files recursively under the ``user_report/`` sub-path.

    Only the new Kiro report format is supported. Legacy ``by_user_analytic/``
    data (Q Developer era) is ignored.

    Handles S3 pagination via *ContinuationToken*.
    """
    s3 = s3_client or boto3.client("s3")
    csv_keys: List[str] = []

    full_prefix = f"{prefix}{NEW_SUBPATH}"
    continuation_token: str | None = None

    while True:
        kwargs: dict = {"Bucket": bucket, "Prefix": full_prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = s3.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            key: str = obj["Key"]
            if key.endswith(".csv"):
                csv_keys.append(key)

        if response.get("IsTruncated"):
            continuation_token = response["NextContinuationToken"]
        else:
            break

    return csv_keys


def read_csv_content(bucket: str, key: str, s3_client=None) -> str:
    """Read the content of a single CSV file from S3 and return it as a string."""
    s3 = s3_client or boto3.client("s3")
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")
