"""Limpa todas as tabelas DynamoDB e o DataBucket do kiro-cost-analyzer.

Preserva os logs do CloudFront (cloudfront-logs/) no DataBucket.
NÃO toca no bucket de origem (source bucket com os CSVs/prompts).

Region and stack name follow ``REGION`` and ``STACK_NAME`` env vars when
provided, falling back to the original defaults to preserve previous
behavior. The Makefile target ``nuke-data`` propagates both.
"""

import os

import boto3

REGION = os.environ.get("REGION", "sa-east-1")
STACK_NAME = os.environ.get("STACK_NAME", "kiro-cost-analyzer")
ACCOUNT_ID = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]

TABLES = [
    f"{STACK_NAME}-analytics",
    f"{STACK_NAME}-processed-files",
    f"{STACK_NAME}-user-names",
    f"{STACK_NAME}-feedback",
]

DATA_BUCKET = f"{STACK_NAME}-data-{ACCOUNT_ID}"
# Prefixes to clean in the DataBucket (app-generated data)
S3_PREFIXES_TO_CLEAN = [
    "prompts-content/",
    "etl-results/",
]

# ── DynamoDB cleanup ────────────────────────────────────────────────────────

dynamodb = boto3.resource("dynamodb", region_name=REGION)

for table_name in TABLES:
    table = dynamodb.Table(table_name)
    key_schema = table.key_schema
    key_names = [k["AttributeName"] for k in key_schema]

    print(f"Limpando {table_name} (keys: {key_names})...")

    count = 0
    kwargs = {}
    while True:
        response = table.scan(
            ProjectionExpression=", ".join(key_names),
            **kwargs,
        )
        items = response.get("Items", [])

        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={k: item[k] for k in key_names})
                count += 1

        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    print(f"  → {count} items deletados.\n")

# ── S3 DataBucket cleanup ───────────────────────────────────────────────────

s3 = boto3.resource("s3", region_name=REGION)
bucket = s3.Bucket(DATA_BUCKET)

print(f"Limpando S3 bucket {DATA_BUCKET}...")

for prefix in S3_PREFIXES_TO_CLEAN:
    count = 0
    for obj in bucket.objects.filter(Prefix=prefix):
        obj.delete()
        count += 1
    print(f"  → {prefix} — {count} objetos deletados.")

print("\nTudo limpo.")
