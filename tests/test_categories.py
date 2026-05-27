"""Tests for ``shared.categories`` — single source of truth for system categories.

The constants in this module ARE the on-disk shape of the ``category`` field
on PROMPT# items. The writer, the categorizer, and the prompts API all
import from here. These tests pin the contract: any change to the values
will break a test, prompting the contributor to plan a backfill or a
transitional matcher rather than silently desync the producers and the
read-side filter.
"""

from __future__ import annotations

from shared.categories import (
    CATEGORY_CLASSIFICATION_ERROR,
    CATEGORY_EMPTY,
    CATEGORY_NOT_CATEGORIZED,
    SYSTEM_CATEGORIES,
)


class TestCategoryLiterals:
    """The literal values are part of the data contract. Changing them
    requires either backfilling existing PROMPT# items or adding a
    transitional matcher that accepts both casings — see the spec at
    ``.kiro/specs/prompt-history-visibility/design.md``."""

    def test_empty_value(self) -> None:
        assert CATEGORY_EMPTY == "Empty"

    def test_not_categorized_value(self) -> None:
        assert CATEGORY_NOT_CATEGORIZED == "NOT_CATEGORIZED"

    def test_classification_error_value(self) -> None:
        assert CATEGORY_CLASSIFICATION_ERROR == "Classification Error"


class TestSystemCategoriesSet:
    def test_membership(self) -> None:
        assert SYSTEM_CATEGORIES == {
            CATEGORY_EMPTY,
            CATEGORY_NOT_CATEGORIZED,
            CATEGORY_CLASSIFICATION_ERROR,
        }

    def test_is_frozen(self) -> None:
        """Immutability prevents accidental mutation at import time, which
        could desync producers and consumers in long-running Lambda warm
        starts."""
        assert isinstance(SYSTEM_CATEGORIES, frozenset)


class TestProducerConsumerParity:
    """Every producer of a system category MUST emit a value that the
    read-side filter recognizes. These tests exercise the actual call sites
    so a refactor that hard-codes a literal would fail here.
    """

    def test_writer_uses_canonical_constant(self) -> None:
        """``etl/writer_handler._write_prompt_record`` uses the canonical
        constant for fresh prompts."""
        # Reading the handler source is the fastest way to assert the
        # writer routes through the constant without spinning up the full
        # Lambda environment.
        import inspect
        from etl import writer_handler

        source = inspect.getsource(writer_handler)
        assert "CATEGORY_NOT_CATEGORIZED" in source
        # The literal must NOT be inlined.
        assert '"NOT_CATEGORIZED"' not in source

    def test_categorizer_uses_canonical_constants(self) -> None:
        """``etl/prompt_categorizer.PromptCategorizer.categorize`` uses the
        canonical constants for both the empty-prompt short-circuit and
        the error fallback."""
        import inspect
        from etl import prompt_categorizer

        source = inspect.getsource(prompt_categorizer)
        assert "CATEGORY_EMPTY" in source
        assert "CATEGORY_CLASSIFICATION_ERROR" in source
        # The literals must NOT be inlined inside the function body. We
        # tolerate them in docstrings (the categorize() docstring lists
        # the possible return values for readers of the API).
        body_line_count = sum(
            1
            for line in source.splitlines()
            if ('"Empty"' in line or '"Classification Error"' in line)
            and not line.lstrip().startswith(('"""', "'''", "#", '"', "'"))
            and "return " in line
        )
        assert body_line_count == 0

    def test_list_uncategorized_uses_canonical_constant(self) -> None:
        """``etl/list_uncategorized_handler`` filters on the canonical
        ``NOT_CATEGORIZED`` constant."""
        import inspect
        from etl import list_uncategorized_handler

        source = inspect.getsource(list_uncategorized_handler)
        assert "CATEGORY_NOT_CATEGORIZED" in source

    def test_prompts_handler_uses_canonical_set(self) -> None:
        """The Prompt History API filters using the canonical
        ``SYSTEM_CATEGORIES`` set, not a private re-declaration."""
        from backend.handlers import prompts_handler

        # The module-level alias must point at the shared frozenset.
        assert prompts_handler._SYSTEM_CATEGORIES is SYSTEM_CATEGORIES
