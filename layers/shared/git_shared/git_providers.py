"""Shared provider constants and helpers for Git integration.

Centralizes the set of supported Git providers, the SSM token path prefix,
token-missing status slugs, and the Mapping_Sort_Key shape so that the
sort key is written, read, and discriminated from a single place instead of
drifting across handlers, the repository layer, and the migrator.
"""

from __future__ import annotations

# Providers this feature supports for repository configuration, user
# mappings, and correlation analysis.
SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"github", "gitlab"})

# Deterministic order for tie-breaking and message rendering.
PROVIDER_ORDER: tuple[str, ...] = ("github", "gitlab")

SSM_TOKEN_PATH_PREFIX = "/kiro-cost-analyzer/git-tokens"

TOKEN_MISSING_SLUG: dict[str, str] = {
    "github": "GITHUB_TOKEN_MISSING",
    "gitlab": "GITLAB_TOKEN_MISSING",
}

MAPPING_SK_PREFIX = "GITMAP#"


def mapping_sort_key(provider: str) -> str:
    """Build the Mapping_Sort_Key for a provider (Requirement 2.5).

    Args:
        provider: Git provider name (e.g. "github", "gitlab").

    Returns:
        The sort key, shaped as ``GITMAP#{provider}``.
    """
    return f"{MAPPING_SK_PREFIX}{provider}"


def is_legacy_mapping_sort_key(sort_key: str) -> bool:
    """True when a sort key uses the Legacy_Mapping_Sort_Key shape.

    Both shapes share the ``GITMAP#`` prefix, so the discriminator is the
    number of separators: ``GITMAP#gitlab`` is current, ``GITMAP#gitlab#alice``
    is legacy. Git provider usernames cannot contain ``#`` on either GitHub or
    GitLab, so a count is sufficient; anything with more than one separator
    is treated as legacy so an unexpected shape migrates rather than being
    silently skipped.

    Args:
        sort_key: The stored item's SK value.

    Returns:
        True if the sort key is a Legacy_Mapping_Sort_Key.
    """
    return sort_key.startswith(MAPPING_SK_PREFIX) and sort_key.count("#") >= 2
