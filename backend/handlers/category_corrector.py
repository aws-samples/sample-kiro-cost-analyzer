"""Category Corrector — applies approved feedback to prompt records and distribution counters.

When a feedback is approved, the corrector:
1. Updates the ``category`` field on the original prompt record.
2. Decrements the counter for the old (original) category.
3. Increments the counter for the new (suggested) category.

All three operations target the Analytics_Table via ``AnalyticsWriter``.
"""

from __future__ import annotations

import os

from shared.sk_normalizer import normalize_sk_value
from shared.analytics_writer import AnalyticsWriter


class CategoryCorrector:
    """Applies approved feedback: updates prompt category and distribution counters.

    Uses ``AnalyticsWriter`` for all DynamoDB mutations on the Analytics_Table.

    Args:
        table_name: Name of the Analytics_Table in DynamoDB.
        dynamodb_resource: Optional boto3 DynamoDB resource (for testing).
    """

    def __init__(self, table_name: str, dynamodb_resource=None):
        self._table_name = table_name
        self._dynamodb_resource = dynamodb_resource
        # AnalyticsWriter requires a data_bucket param; pass empty string
        # since category correction never touches S3 content.
        self._writer = AnalyticsWriter(
            table_name=table_name,
            data_bucket="",
            dynamodb_resource=dynamodb_resource,
        )

    def apply_correction(self, feedback: dict) -> None:
        """Update prompt category and adjust STATS#CATEGORY# counters.

        Performs three atomic DynamoDB operations:
        1. SET the ``category`` field on the original prompt to the suggested value.
        2. ADD -1 to the counter for the original (old) category.
        3. ADD +1 to the counter for the new (suggested) category.

        Args:
            feedback: A feedback record dict containing at least:
                - ``promptPK``: Partition key of the prompt (e.g. ``USER#{userId}``).
                - ``promptSK``: Sort key of the prompt.
                - ``originalCategory``: The category being replaced.
                - ``suggestedCategory``: The corrected category to apply.
        """
        prompt_pk = feedback["promptPK"]
        prompt_sk = feedback["promptSK"]
        original_category = feedback["originalCategory"]
        suggested_category = feedback["suggestedCategory"]

        # Extract userId from PK (format: "USER#{userId}")
        user_id = prompt_pk.split("#", 1)[1] if "#" in prompt_pk else prompt_pk

        # Normalize categories for the STATS#CATEGORY# sort keys
        normalized_old = normalize_sk_value(original_category)
        normalized_new = normalize_sk_value(suggested_category)

        # 1. Update the category field on the prompt record
        self._writer.update_prompt_category(prompt_pk, prompt_sk, suggested_category)

        # 2. Decrement the old category counter
        self._writer.decrement_category_count(user_id, normalized_old)

        # 3. Increment the new category counter
        self._writer.increment_category_count(user_id, normalized_new, suggested_category)
