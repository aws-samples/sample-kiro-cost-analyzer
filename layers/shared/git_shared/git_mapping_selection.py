"""Shared selection rule for surviving Git user mappings.

Both the correlation handler and the mapping migrator sometimes face more
than one candidate mapping for a single (userId, provider) pair — the
correlation handler while legacy-keyed items still coexist with the new
key shape, the migrator while collapsing legacy items during migration.
This module is the single place that rule is written, so the two
components cannot disagree about which mapping wins.
"""

from __future__ import annotations


def select_mapping(candidates: list[dict]) -> dict:
    """Pick the surviving mapping from a non-empty set of candidates for one
    (userId, provider) pair.

    Newest ``createdAt`` wins (Requirements 7.9, 11.2). On equal
    ``createdAt``, the lexicographically smallest ``gitUsername`` wins
    (Requirement 11.3), so the survivor is a function of the stored data
    alone — no timestamp, no read order, no insertion order. A missing
    ``createdAt`` sorts as the empty string, which makes it the oldest
    rather than an error.

    The two-stage form (max, then min over the tied set) is deliberate:
    the rule mixes directions (newest timestamp, smallest username), which
    a single ``sorted(..., reverse=True)`` cannot express without also
    reversing the tie-break.

    Args:
        candidates: Non-empty list of mapping dicts for the same
            (userId, provider) pair.

    Returns:
        The single mapping dict that survives the selection rule.
    """
    newest = max(m.get("createdAt", "") for m in candidates)
    tied = [m for m in candidates if m.get("createdAt", "") == newest]
    return min(tied, key=lambda m: m.get("gitUsername", ""))
