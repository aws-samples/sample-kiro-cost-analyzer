"""Tests for scripts/promote_changelog.py (Feature: release-automation).

Feature: release-automation, Property 1: Bump arithmetic
Feature: release-automation, Property 2: Changelog conservation
Feature: release-automation, Property 3: Empty-release refusal
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
from hypothesis import given, strategies as st

_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "promote_changelog.py"
_spec = importlib.util.spec_from_file_location("promote_changelog", _SCRIPT)
promote_changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(promote_changelog)

bump_version = promote_changelog.bump_version
promote_text = promote_changelog.promote_text
extract_section = promote_changelog.extract_section


SAMPLE = """# Changelog

## Unreleased

### Fix — Something small

- A fix line.

## v3.4 — Prior Release (2026-08-17)

- Old entry.
"""


class TestBumpArithmetic:
    """Feature: release-automation, Property 1: Bump arithmetic."""

    @given(major=st.integers(0, 999), minor=st.integers(0, 999))
    def test_bump_property(self, major: int, minor: int) -> None:
        version = f"{major}.{minor}"
        assert bump_version(version, "major") == f"{major + 1}.0"
        assert bump_version(version, "minor") == f"{major}.{minor + 1}"
        assert bump_version(version, "patch") == f"{major}.{minor}.1"

    @given(major=st.integers(0, 999), minor=st.integers(0, 999), patch=st.integers(0, 999))
    def test_bump_property_three_part(self, major: int, minor: int, patch: int) -> None:
        version = f"{major}.{minor}.{patch}"
        assert bump_version(version, "patch") == f"{major}.{minor}.{patch + 1}"
        assert bump_version(version, "minor") == f"{major}.{minor + 1}"

    def test_examples(self) -> None:
        assert bump_version("3.4", "minor") == "3.5"
        assert bump_version("3.4", "patch") == "3.4.1"
        assert bump_version("3.4", "major") == "4.0"
        assert bump_version("3.1.2", "patch") == "3.1.3"

    def test_malformed_raises(self) -> None:
        with pytest.raises(ValueError):
            bump_version("not-a-version", "minor")
        with pytest.raises(ValueError):
            bump_version("3.4", "mega")


class TestChangelogConservation:
    """Feature: release-automation, Property 2: Changelog conservation."""

    def test_promotion_preserves_content_and_prior_sections(self) -> None:
        result = promote_text(SAMPLE, "3.5", "New Release", "2026-08-18")

        # New heading present with promoted content beneath it
        assert "## v3.5 — New Release (2026-08-18)" in result
        assert "### Fix — Something small" in result
        assert "- A fix line." in result
        # Fresh empty Unreleased above the new version
        unreleased_pos = result.find("## Unreleased")
        new_version_pos = result.find("## v3.5")
        assert -1 < unreleased_pos < new_version_pos
        # Prior sections unchanged
        assert "## v3.4 — Prior Release (2026-08-17)" in result
        assert "- Old entry." in result

    def test_extract_returns_promoted_body(self) -> None:
        promoted = promote_text(SAMPLE, "3.5", "New Release", "2026-08-18")
        body = extract_section(promoted, "3.5")
        assert "- A fix line." in body
        assert "## v3.5" not in body  # heading excluded
        assert "- Old entry." not in body  # next section excluded


class TestEmptyReleaseRefusal:
    """Feature: release-automation, Property 3: Empty-release refusal."""

    def test_empty_unreleased_raises(self) -> None:
        empty = "# Changelog\n\n## Unreleased\n\n## v3.4 — Prior (2026-08-17)\n\n- Old.\n"
        with pytest.raises(ValueError, match="empty"):
            promote_text(empty, "3.5", "Title", "2026-08-18")

    def test_missing_unreleased_raises(self) -> None:
        with pytest.raises(ValueError, match="No '## Unreleased'"):
            promote_text("# Changelog\n\n## v3.4 — X (2026-01-01)\n", "3.5", "T", "2026-08-18")
