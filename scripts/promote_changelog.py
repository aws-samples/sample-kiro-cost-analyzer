#!/usr/bin/env python3
"""Promote the changelog's Unreleased section to a new version.

Single source of truth for release mechanics (Feature: release-automation):

- ``--bump {major,minor,patch}`` computes the next version from the root
  ``VERSION`` file (major: X+1.0; minor: X.Y+1; patch: X.Y.Z+1 with Z=0
  assumed when absent).
- Promotion rewrites ``docs/changelog.md``: the ``## Unreleased`` heading
  becomes ``## v{next} — {title} ({date})`` and a fresh empty
  ``## Unreleased`` section is inserted above it. Fails (exit 1, no writes)
  when the Unreleased section has no content.
- ``--extract VERSION`` prints an existing version's section body (used by
  the publish workflow as GitHub Release notes).

Usage:
    promote_changelog.py --bump minor --title "Release title" [--date YYYY-MM-DD] [--dry-run]
    promote_changelog.py --extract 3.5
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "docs" / "changelog.md"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")
_HEADING_RE = re.compile(r"^## ", re.MULTILINE)


def bump_version(current: str, bump: str) -> str:
    """Returns the next version string for the given bump type.

    Args:
        current: Current version, ``MAJOR.MINOR`` or ``MAJOR.MINOR.PATCH``.
        bump: One of ``major``, ``minor``, ``patch``.

    Raises:
        ValueError: If the current version does not parse or bump is unknown.
    """
    match = _VERSION_RE.match(current.strip())
    if not match:
        raise ValueError(f"Malformed version: {current!r} (expected MAJOR.MINOR[.PATCH])")
    major, minor = int(match.group(1)), int(match.group(2))
    patch = int(match.group(3)) if match.group(3) else 0

    if bump == "major":
        return f"{major + 1}.0"
    if bump == "minor":
        return f"{major}.{minor + 1}"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unknown bump type: {bump!r}")


def promote_text(changelog: str, new_version: str, title: str, date: str) -> str:
    """Returns the changelog text with Unreleased promoted to the new version.

    Raises:
        ValueError: If there is no Unreleased section or it is empty.
    """
    marker = "## Unreleased"
    start = changelog.find(marker)
    if start == -1:
        raise ValueError("No '## Unreleased' section found in the changelog.")

    body_start = start + len(marker)
    next_heading = _HEADING_RE.search(changelog, body_start)
    body_end = next_heading.start() if next_heading else len(changelog)
    section_body = changelog[body_start:body_end]

    if not any(line.strip() for line in section_body.splitlines()):
        raise ValueError("The Unreleased section is empty — nothing to release.")

    new_heading = f"## v{new_version} — {title} ({date})"
    return (
        changelog[:start]
        + f"{marker}\n\n"
        + new_heading
        + changelog[body_start:]
    )


def extract_section(changelog: str, version: str) -> str:
    """Returns the body of an existing version section (without its heading).

    Raises:
        ValueError: If no heading for the version exists.
    """
    heading_re = re.compile(rf"^## v{re.escape(version)} — .*$", re.MULTILINE)
    match = heading_re.search(changelog)
    if not match:
        raise ValueError(f"No changelog section found for version {version}.")
    body_start = match.end()
    next_heading = _HEADING_RE.search(changelog, body_start)
    body_end = next_heading.start() if next_heading else len(changelog)
    return changelog[body_start:body_end].strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bump", choices=["major", "minor", "patch"])
    group.add_argument("--extract", metavar="VERSION")
    parser.add_argument("--title", help="Release title (required with --bump)")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    changelog = CHANGELOG_FILE.read_text(encoding="utf-8")

    if args.extract:
        try:
            sys.stdout.write(extract_section(changelog, args.extract))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    if not args.title:
        print("error: --title is required with --bump", file=sys.stderr)
        return 1

    current = VERSION_FILE.read_text(encoding="utf-8").strip()
    try:
        new_version = bump_version(current, args.bump)
        promoted = promote_text(changelog, new_version, args.title, args.date)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"dry-run: {current} -> {new_version} (no files written)", file=sys.stderr)
    else:
        VERSION_FILE.write_text(f"{new_version}\n", encoding="utf-8")
        CHANGELOG_FILE.write_text(promoted, encoding="utf-8")

    print(new_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
