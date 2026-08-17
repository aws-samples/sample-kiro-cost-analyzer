"""Doc-content smoke test for the S3 source config read-only documentation update.

Regression guard confirming the documentation changes made by the
s3-source-config-readonly feature (design task 8) landed and stayed landed:

- `docs/security.md` no longer describes the `ValidateSourceBucket` wildcard
  grant as an open, planned-but-not-implemented finding, and now records
  that changing the source bucket/prefixes requires a redeploy.
- `docs/changelog.md` no longer carries the old "TODO (planned, not yet
  implemented)" heading for the source-bucket hot-swap removal verbatim, and
  keeps an entry mentioning `ValidateSourceBucket` (originally under
  `## Unreleased`, promoted to a versioned section on release).

Follows the `Path(__file__).resolve().parent.parent` repo-root resolution
pattern used elsewhere in this suite (e.g.
`tests/test_s3_source_config_readonly_template.py`,
`tests/test_backend_english_only.py`).

Feature: s3-source-config-readonly (design task 8.4).
Requirements: 8.1, 8.2, 8.3, 8.4.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURITY_DOC_PATH = REPO_ROOT / "docs" / "security.md"
CHANGELOG_DOC_PATH = REPO_ROOT / "docs" / "changelog.md"


@pytest.fixture(scope="module")
def security_doc_text() -> str:
    assert SECURITY_DOC_PATH.is_file(), f"docs/security.md not found at {SECURITY_DOC_PATH}"
    return SECURITY_DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def changelog_doc_text() -> str:
    assert CHANGELOG_DOC_PATH.is_file(), f"docs/changelog.md not found at {CHANGELOG_DOC_PATH}"
    return CHANGELOG_DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# docs/security.md (Requirements 8.1, 8.2)
# ---------------------------------------------------------------------------


def test_security_doc_no_longer_describes_finding_as_planned(security_doc_text: str) -> None:
    """The old 'open, planned fix' framing is gone from docs/security.md."""
    assert "Known finding, planned fix" not in security_doc_text, (
        "docs/security.md must not describe the ValidateSourceBucket wildcard "
        "grant as an open, planned-but-not-implemented finding"
    )


def test_security_doc_mentions_redeploy_requirement(security_doc_text: str) -> None:
    """docs/security.md records that changing the source bucket now requires a redeploy."""
    assert "redeploy" in security_doc_text.lower(), (
        "docs/security.md must reference the redeploy requirement for changing "
        "the source bucket/prefixes after this feature's removal of the write path"
    )


# ---------------------------------------------------------------------------
# docs/changelog.md (Requirements 8.3, 8.4)
# ---------------------------------------------------------------------------


def test_changelog_doc_no_longer_has_planned_todo_heading(changelog_doc_text: str) -> None:
    """The old planned-but-not-implemented TODO heading is gone verbatim."""
    assert (
        "### TODO (planned, not yet implemented) — Remove the source-bucket "
        "hot-swap feature"
    ) not in changelog_doc_text, (
        "docs/changelog.md must not retain the old planned-but-not-implemented "
        "TODO heading verbatim; it must be removed or rewritten to reflect "
        "completion"
    )


def test_changelog_doc_has_entry_mentioning_validate_source_bucket(
    changelog_doc_text: str,
) -> None:
    """A changelog entry describes the ValidateSourceBucket removal.

    The entry originally lived under ``## Unreleased``; release promotions
    (e.g. v3.4) move it under a versioned heading, so this guard only
    requires the mention to exist somewhere in the changelog.
    """
    assert "ValidateSourceBucket" in changelog_doc_text, (
        "docs/changelog.md must mention ValidateSourceBucket (the removal of "
        "its wildcard IAM grant must stay documented)"
    )
