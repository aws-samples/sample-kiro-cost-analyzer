"""Prompt category constants shared by writer, categorizer, and read paths.

This module is the single source of truth for the *system* prompt categories
written to DynamoDB. The writer, the categorizer, the prompts API, and any
read-side filter (Python or, indirectly, the frontend) MUST all import from
here instead of inlining string literals.

The motivating bug: ``backend/handlers/prompts_handler.py`` previously
declared a lowercase ``_SYSTEM_CATEGORIES`` set while the writer and
categorizer wrote mixed-case values (``Empty``, ``NOT_CATEGORIZED``,
``Classification Error``). DynamoDB ``Attr.ne()`` filters are case-sensitive,
so the FilterExpression silently failed and the Prompt History table
rendered empty even when the dataset had thousands of meaningful prompts.

These constants ARE the on-disk shape. Changing them requires either a
backfill of existing PROMPT# items or a transitional matcher that accepts
both casings. See ``.kiro/specs/prompt-history-visibility/design.md``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Individual category labels — exact string written to DynamoDB
# ---------------------------------------------------------------------------

#: Set on freshly ingested prompts by ``etl/writer_handler.py`` before the
#: Bedrock categorizer has run. ``etl/list_uncategorized_handler.py`` scans
#: for this exact value.
CATEGORY_NOT_CATEGORIZED = "NOT_CATEGORIZED"

#: Returned by :class:`PromptCategorizer` when the prompt body is empty or
#: whitespace-only. The Git correlation agent and the prompts API both
#: filter this out by default — these are turn-by-turn conversation
#: fragments with no meaningful content.
CATEGORY_EMPTY = "Empty"

#: Returned by :class:`PromptCategorizer` when Bedrock returns a value
#: outside the allowed taxonomy or fails after retries.
CATEGORY_CLASSIFICATION_ERROR = "Classification Error"


# ---------------------------------------------------------------------------
# Aggregate sets — for filtering on the read path
# ---------------------------------------------------------------------------

#: Categories considered non-meaningful. Excluded from the default Prompt
#: History listing and from agent-side aggregations. Use this set with
#: ``Attr.ne()`` chains in DynamoDB queries — the casing here MUST match
#: what the writer actually emits because DynamoDB filters are byte-exact.
SYSTEM_CATEGORIES: frozenset[str] = frozenset(
    {
        CATEGORY_EMPTY,
        CATEGORY_NOT_CATEGORIZED,
        CATEGORY_CLASSIFICATION_ERROR,
    }
)
