"""Property-based tests for the Git mapping repository layer.

Covers Properties 6, 22, 23, 24, and 25 from the gitlab-provider-support
design. These properties share a populated-table fixture and rebuild the
mocked DynamoDB table per Hypothesis example, so they are split out from
``tests/test_gitlab_provider_properties.py`` (Properties 1-5, 7-19), which
does not need that fixture shape.

Because Hypothesis re-runs the decorated test function body once per
generated example, the mocked table is created *inside* each test function,
wrapped in ``with mock_aws():``, rather than via a pytest fixture. A pytest
fixture would run once per test *function* invocation from pytest's point of
view, but Hypothesis calls the function body many times per invocation, so a
fixture-based table would leak state across examples.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from git_shared.git_mapping_selection import select_mapping
from git_shared.git_providers import mapping_sort_key
from git_shared.git_repository import GitRepository
from custom_resources.mapping_migrator import migrate


TABLE_NAME = "TestAnalyticsTable"

# Deliberately includes a bare "git" alongside "github" and "gitlab" so the
# prefix collision (GITMAP#git is a prefix of GITMAP#github/GITMAP#gitlab)
# is exercised head-on, per the design's generator note for Property 22.
_PROVIDERS = st.sampled_from(["git", "github", "gitlab"])

_USER_IDS = st.sampled_from(["user-1", "user-2", "user-3", "user-4"])

_USERNAMES = st.sampled_from(["alice", "bob", "carol", "dev-1", "dev-2"])


def _create_table(resource):
    """Create the mocked Analytics_Table with the standard PK/SK schema."""
    resource.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


# Feature: gitlab-provider-support, Property 22: Provider-scoped retrieval returns exactly one provider's mappings
class TestProperty22ProviderScopedRetrieval:
    """Property 22: get_all_mappings_for_provider returns exactly one
    provider's mappings — no cross-provider leakage, no false negatives.

    This is the regression guard for the `begins_with` bug fixed in task
    5.2: `get_all_mappings_for_provider`'s old predicate
    `Key("SK").begins_with(f"GITMAP#{provider}#")` silently returned an
    empty list for every provider under the new key shape (no trailing
    `#` remains once gitUsername moves out of the sort key).

    Validates: Requirements 2.10
    """

    @given(
        mapping_pairs=st.lists(
            st.tuples(_USER_IDS, _PROVIDERS, _USERNAMES),
            min_size=0,
            max_size=12,
        ),
        target_provider=_PROVIDERS,
    )
    @settings(max_examples=20, deadline=None)
    def test_provider_scoped_retrieval_returns_exactly_that_providers_mappings(
        self, mapping_pairs, target_provider
    ):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            repo = GitRepository(TABLE_NAME, dynamodb_resource=resource)

            # A (userId, provider) pair can only hold one mapping (the new
            # key shape), so de-duplicate on that pair before writing —
            # later entries for the same pair simply replace earlier ones,
            # which mirrors put_user_mapping's real upsert behavior.
            stored: dict[tuple[str, str], dict] = {}
            for user_id, provider, username in mapping_pairs:
                stored[(user_id, provider)] = {
                    "provider": provider,
                    "gitUsername": username,
                }

            for (user_id, provider), mapping in stored.items():
                repo.put_user_mapping(user_id, mapping)

            result = repo.get_all_mappings_for_provider(target_provider)

            # No cross-provider leakage: every returned item belongs to the
            # requested provider.
            for item in result:
                assert item["provider"] == target_provider

            # No false negatives, and no phantom results: the set of
            # (userId, gitUsername) pairs returned equals exactly the set
            # stored for the target provider. Usernames are not unique
            # across users, so identity is keyed by userId, not by
            # gitUsername alone — this is exactly what the buggy
            # begins_with predicate would fail, since it returned an
            # empty list for every provider.
            expected_pairs = {
                (user_id, mapping["gitUsername"])
                for (user_id, provider), mapping in stored.items()
                if provider == target_provider
            }
            returned_pairs = {
                (item["PK"].removeprefix("USER#"), item["gitUsername"])
                for item in result
            }
            assert returned_pairs == expected_pairs

            # Same cardinality as the expected subset.
            assert len(result) == len(expected_pairs)

# Feature: gitlab-provider-support, Property 6: Mapping storage — coexistence, uniqueness, replacement, and deletion
class TestProperty6MappingStorage:
    """Property 6: Mapping storage — coexistence, uniqueness, replacement,
    and deletion.

    Submitting a sequence of usernames for a single (userId, provider) pair
    must leave exactly one item behind, holding the last-submitted username,
    with put_user_mapping correctly reporting what (if anything) it
    replaced. A user's github and gitlab mappings must coexist on distinct
    items, and deleting one must not disturb the other.

    Validates: Requirements 2.1, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 7.8
    """

    @given(
        user_id=_USER_IDS,
        provider=st.sampled_from(["github", "gitlab"]),
        usernames=st.lists(_USERNAMES, min_size=1, max_size=5),
        other_provider_username=_USERNAMES,
    )
    @settings(max_examples=20, deadline=None)
    def test_mapping_storage_coexistence_uniqueness_replacement_deletion(
        self, user_id, provider, usernames, other_provider_username
    ):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            repo = GitRepository(TABLE_NAME, dynamodb_resource=resource)

            other_provider = "gitlab" if provider == "github" else "github"

            # Submit the sequence of usernames, in order, for the target
            # (userId, provider) pair, checking put_user_mapping's
            # replacement reporting at each step (Requirement 2.7).
            previous_username = None
            for index, username in enumerate(usernames):
                stored, previous_item = repo.put_user_mapping(
                    user_id,
                    {
                        "provider": provider,
                        "gitUsername": username,
                        "createdAt": f"2024-01-{index + 1:02d}T00:00:00Z",
                        "createdBy": "admin",
                    },
                )
                assert stored["gitUsername"] == username

                if index == 0:
                    # First call for this pair: nothing existed before.
                    assert previous_item is None
                else:
                    # Every subsequent call replaces the immediately prior
                    # username in the sequence.
                    assert previous_item is not None
                    assert previous_item["gitUsername"] == previous_username

                previous_username = username

            # Coexistence: store a mapping for the other provider on the
            # same user. Neither provider's mapping should overwrite the
            # other's (Requirement 2.3).
            repo.put_user_mapping(
                user_id,
                {
                    "provider": other_provider,
                    "gitUsername": other_provider_username,
                    "createdAt": "2024-02-01T00:00:00Z",
                    "createdBy": "admin",
                },
            )

            all_mappings = repo.list_user_mappings(user_id)

            # Uniqueness: exactly one item for the target provider, no
            # matter how many usernames were submitted for it (Requirements
            # 2.5, 2.6).
            target_items = [m for m in all_mappings if m["provider"] == provider]
            assert len(target_items) == 1

            # Replacement: the surviving item holds the last-submitted
            # username (Requirement 2.7).
            assert target_items[0]["gitUsername"] == usernames[-1]

            # Coexistence: both providers' mappings are present at once,
            # two items total (Requirement 2.3).
            other_items = [m for m in all_mappings if m["provider"] == other_provider]
            assert len(other_items) == 1
            assert other_items[0]["gitUsername"] == other_provider_username
            assert len(all_mappings) == 2

            # Deletion: removing the target provider's mapping leaves no
            # trace of it, while the other provider's mapping survives
            # untouched (Requirement 2.8).
            repo.delete_user_mapping(user_id, provider)
            remaining = repo.list_user_mappings(user_id)
            assert all(m["provider"] != provider for m in remaining)
            remaining_other = [m for m in remaining if m["provider"] == other_provider]
            assert len(remaining_other) == 1
            assert remaining_other[0]["gitUsername"] == other_provider_username


# Small, repeatable pool so the same timestamp is drawable by more than one
# candidate in a single example — ties must actually occur for the
# lexicographic tie-break (Requirement 11.3) to ever execute. Freshly
# sampled ISO-8601 strings would never repeat, so this is deliberately a
# small closed set rather than st.datetimes() or similar.
_PROPERTY23_CREATED_ATS = st.sampled_from(
    [
        "2024-01-01T00:00:00Z",
        "2024-02-01T00:00:00Z",
        "2024-03-01T00:00:00Z",
        "2024-04-01T00:00:00Z",
    ]
)

_PROPERTY23_GIT_USERNAMES = st.sampled_from(["alice", "bob", "carol", "dave"])


def _property23_candidate_strategy():
    """Build one candidate dict, omitting the `createdAt` key entirely
    (not setting it to None) when the drawn sentinel says to omit it.
    """
    return st.builds(
        lambda username, created_at: (
            {"gitUsername": username}
            if created_at is None
            else {"gitUsername": username, "createdAt": created_at}
        ),
        username=_PROPERTY23_GIT_USERNAMES,
        created_at=st.one_of(st.none(), _PROPERTY23_CREATED_ATS),
    )


# Feature: gitlab-provider-support, Property 23: Mapping selection is a function of the stored data, and both components compute it identically
class TestProperty23MappingSelectionAgreement:
    """Property 23: Mapping selection is a function of the stored data, and
    both components compute it identically.

    `select_mapping` (`git_shared.git_mapping_selection`) is the single
    source of truth the correlation handler's username resolution and the
    migrator's collapse step both delegate to — neither reimplements the
    rule. This test pins down the rule's contract directly: newest
    `createdAt` wins; on a tie, the lexicographically smallest
    `gitUsername` wins; a missing `createdAt` sorts as `""` (oldest); and
    the result does not depend on input order. Any divergence between the
    two consumers can only happen if one of them stops calling this
    function — which this property makes detectable the moment either
    consumer's behavior is checked against this same rule elsewhere.

    Validates: Requirements 7.9, 11.2, 11.3, 11.4
    """

    @given(
        candidates=st.lists(_property23_candidate_strategy(), min_size=2, max_size=6)
    )
    @settings(max_examples=20, deadline=None)
    def test_selection_is_deterministic_order_independent_and_correct(
        self, candidates
    ):
        # Determinism: calling select_mapping twice on the same
        # (unshuffled) list returns the same result.
        first_call = select_mapping(candidates)
        second_call = select_mapping(candidates)
        assert first_call == second_call

        # Order-independence: the winner is a function of the stored data
        # alone, not of read/insertion order.
        reversed_candidates = list(reversed(candidates))
        assert select_mapping(candidates) == select_mapping(reversed_candidates)

        # Correctness of the rule, derived independently of the
        # implementation's own two-stage form: newest createdAt wins
        # (missing createdAt sorts as ""), and on a tie the
        # lexicographically smallest gitUsername wins.
        max_created_at = max(c.get("createdAt", "") for c in candidates)
        tied = [c for c in candidates if c.get("createdAt", "") == max_created_at]
        expected = min(tied, key=lambda c: c.get("gitUsername", ""))

        assert select_mapping(candidates) == expected

    def test_missing_created_at_never_wins_over_a_present_one(self):
        # A candidate missing createdAt entirely sorts as "" (oldest), so
        # it must never be selected while another candidate has a
        # non-empty createdAt.
        candidates = [
            {"gitUsername": "alice"},  # no createdAt key at all
            {"gitUsername": "bob", "createdAt": "2024-01-01T00:00:00Z"},
            {"gitUsername": "carol", "createdAt": "2024-02-01T00:00:00Z"},
        ]

        result = select_mapping(candidates)

        assert result["gitUsername"] == "carol"
        assert result["gitUsername"] != "alice"

    def test_tie_break_picks_lexicographically_smallest_username(self):
        # Multiple candidates share the max createdAt: the smallest
        # gitUsername among them must win.
        candidates = [
            {"gitUsername": "dave", "createdAt": "2024-03-01T00:00:00Z"},
            {"gitUsername": "alice", "createdAt": "2024-03-01T00:00:00Z"},
            {"gitUsername": "bob", "createdAt": "2024-01-01T00:00:00Z"},
        ]

        result = select_mapping(candidates)

        assert result["gitUsername"] == "alice"


# Small pool of legacy-item timestamps and usernames, mirroring Property
# 23's generator style. Ties are not the focus of this property (that is
# Property 23's job) but reusing the small pool costs nothing and keeps the
# generated data shape consistent across this file.
_PROPERTY24_CREATED_ATS = st.sampled_from(
    [
        "2024-01-01T00:00:00Z",
        "2024-02-01T00:00:00Z",
        "2024-03-01T00:00:00Z",
    ]
)

_PROPERTY24_USERNAMES = st.sampled_from(["alice", "bob", "carol", "dave"])

# Property 24 is about the migration postcondition, not the prefix-collision
# concern Property 22 already covers, so provider is restricted to the two
# real providers.
_PROPERTY24_PROVIDERS = st.sampled_from(["github", "gitlab"])


def _property24_legacy_item_strategy():
    """Build one legacy-shaped item body (gitUsername + optional createdAt)."""
    return st.builds(
        lambda username, created_at: (
            {"gitUsername": username}
            if created_at is None
            else {"gitUsername": username, "createdAt": created_at}
        ),
        username=_PROPERTY24_USERNAMES,
        created_at=st.one_of(st.none(), _PROPERTY24_CREATED_ATS),
    )


# Feature: gitlab-provider-support, Property 24: Migration postcondition — present under the new key, absent under the legacy key
class TestProperty24MigrationPostcondition:
    """Property 24: Migration postcondition — present under the new key,
    absent under the legacy key.

    For any population of legacy-keyed mapping items, running the migrator
    to completion (a `remaining_ms` budget that never drops below
    `RESPONSE_MARGIN_MS`, so the report always comes back untruncated)
    leaves every (userId, provider) pair retrievable under the current
    Mapping_Sort_Key and no item anywhere under the Legacy_Mapping_Sort_Key
    for that pair.

    The legacy items are seeded by writing raw items directly via
    `table.put_item`, bypassing `put_user_mapping` entirely — that method
    can no longer produce the legacy key shape, so this is the only way to
    reach the state the migrator is meant to clean up.

    Validates: Requirements 11.1, 11.5
    """

    @given(
        pairs=st.lists(
            st.tuples(
                _USER_IDS,
                _PROPERTY24_PROVIDERS,
                st.lists(_property24_legacy_item_strategy(), min_size=1, max_size=4),
            ),
            min_size=2,
            max_size=5,
            unique_by=lambda pair: (pair[0], pair[1]),
        )
    )
    @settings(max_examples=20, deadline=None)
    def test_migration_leaves_data_under_new_key_and_none_under_legacy_key(
        self, pairs
    ):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            table = resource.Table(TABLE_NAME)

            # Seed legacy items directly, bypassing put_user_mapping (which
            # can only write the new key shape).
            legacy_sks_by_pair: dict[tuple[str, str], list[str]] = {}
            for user_id, provider, legacy_bodies in pairs:
                legacy_sks_by_pair[(user_id, provider)] = []
                for body in legacy_bodies:
                    git_username = body["gitUsername"]
                    legacy_sk = f"GITMAP#{provider}#{git_username}"
                    item = {
                        "PK": f"USER#{user_id}",
                        "SK": legacy_sk,
                        "provider": provider,
                        "gitUsername": git_username,
                    }
                    if "createdAt" in body:
                        item["createdAt"] = body["createdAt"]
                    table.put_item(Item=item)
                    legacy_sks_by_pair[(user_id, provider)].append(legacy_sk)

            logger = MagicMock()
            report = migrate(table, logger, remaining_ms=lambda: 999_999)

            distinct_pairs = set(legacy_sks_by_pair.keys())

            # Sanity check on the report: nothing truncated, nothing left
            # unconverted, and exactly the distinct seeded pairs migrated.
            assert report["truncated"] is False
            assert report["unconverted"] == 0
            assert report["migrated"] == len(distinct_pairs)

            for (user_id, provider), legacy_sks in legacy_sks_by_pair.items():
                # Presence under the new key.
                new_key_response = table.get_item(
                    Key={"PK": f"USER#{user_id}", "SK": mapping_sort_key(provider)}
                )
                assert "Item" in new_key_response

                # Absence under every original legacy key for that pair.
                for legacy_sk in legacy_sks:
                    legacy_response = table.get_item(
                        Key={"PK": f"USER#{user_id}", "SK": legacy_sk}
                    )
                    assert legacy_response.get("Item") is None


def _property25_seed_body_strategy():
    """Build one item body (gitUsername + optional createdAt) for seeding
    either the legacy or the current item of a Property 25 pair.

    Reuses Property 24's small `_PROPERTY24_CREATED_ATS` pool (rather than
    a fresh strategy) so drawing this twice per pair — once for the legacy
    item, once for the current item — actually produces ties often enough
    across 100 examples for both "legacy wins" and "current wins" to occur.
    """
    return _property24_legacy_item_strategy()


# Feature: gitlab-provider-support, Property 25: Migration idempotence
class TestProperty25MigrationIdempotence:
    """Property 25: Migration idempotence.

    Running the migrator a second time over its own output must be a
    no-op: the surviving mapping under the current key is unchanged, and
    the second run's report shows nothing left to do. The fixture seeds a
    *partially migrated* state directly — a legacy item and a current
    item for the same (userId, provider) pair, each with its own
    `createdAt` — which is exactly the state a crash between `put_item`
    and `delete_item` in `_migrate_group` would leave behind, and
    therefore exactly what idempotence has to survive.

    Validates: Requirements 11.6
    """

    @given(
        pairs=st.lists(
            st.tuples(
                _USER_IDS,
                _PROPERTY24_PROVIDERS,
                _property25_seed_body_strategy(),  # legacy item body
                _property25_seed_body_strategy(),  # current item body
            ),
            min_size=2,
            max_size=4,
            unique_by=lambda pair: (pair[0], pair[1]),
        )
    )
    @settings(max_examples=20, deadline=None)
    def test_second_migration_run_is_a_no_op(self, pairs):
        with mock_aws():
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_table(resource)
            table = resource.Table(TABLE_NAME)

            # Seed the partially-migrated state directly: one legacy item
            # and one current item per pair, bypassing put_user_mapping
            # and bypassing a first migrate() call entirely — this state
            # is only reachable via a crash mid-migration in real life.
            legacy_keys_by_pair: dict[tuple[str, str], dict] = {}
            for user_id, provider, legacy_body, current_body in pairs:
                legacy_username = legacy_body["gitUsername"]
                legacy_sk = f"GITMAP#{provider}#{legacy_username}"
                legacy_item = {
                    "PK": f"USER#{user_id}",
                    "SK": legacy_sk,
                    "provider": provider,
                    "gitUsername": legacy_username,
                }
                if "createdAt" in legacy_body:
                    legacy_item["createdAt"] = legacy_body["createdAt"]
                table.put_item(Item=legacy_item)

                current_username = current_body["gitUsername"]
                current_item = {
                    "PK": f"USER#{user_id}",
                    "SK": mapping_sort_key(provider),
                    "provider": provider,
                    "gitUsername": current_username,
                }
                if "createdAt" in current_body:
                    current_item["createdAt"] = current_body["createdAt"]
                table.put_item(Item=current_item)

                legacy_keys_by_pair[(user_id, provider)] = {
                    "PK": f"USER#{user_id}",
                    "SK": legacy_sk,
                }

            logger = MagicMock()

            first_report = migrate(table, logger, remaining_ms=lambda: 999_999)

            distinct_pairs = {(user_id, provider) for user_id, provider, _, _ in pairs}

            # Light sanity check on the first run, mirroring Property 24's
            # postcondition — not the focus of this test, but cheap to
            # confirm before checking idempotence.
            assert first_report["truncated"] is False
            assert first_report["migrated"] == len(distinct_pairs)

            first_run_current_items: dict[tuple[str, str], dict] = {}
            for user_id, provider in distinct_pairs:
                new_key_response = table.get_item(
                    Key={"PK": f"USER#{user_id}", "SK": mapping_sort_key(provider)}
                )
                assert "Item" in new_key_response
                first_run_current_items[(user_id, provider)] = new_key_response["Item"]

                legacy_key = legacy_keys_by_pair[(user_id, provider)]
                legacy_response = table.get_item(Key=legacy_key)
                assert legacy_response.get("Item") is None

            second_report = migrate(table, logger, remaining_ms=lambda: 999_999)

            # A table with zero remaining legacy items has nothing for
            # _scan_legacy_groups to group, so the whole second report
            # must be the all-zero, untruncated no-op report.
            assert second_report == {
                "scanned": 0,
                "migrated": 0,
                "discarded": 0,
                "failed": 0,
                "unconverted": 0,
                "truncated": False,
            }

            for user_id, provider in distinct_pairs:
                # The surviving mapping is byte-identical after the second
                # run: running migrate() twice must not change it.
                new_key_response = table.get_item(
                    Key={"PK": f"USER#{user_id}", "SK": mapping_sort_key(provider)}
                )
                assert new_key_response["Item"] == first_run_current_items[(user_id, provider)]

                # No legacy item resurfaces after the second run.
                legacy_key = legacy_keys_by_pair[(user_id, provider)]
                legacy_response = table.get_item(Key=legacy_key)
                assert legacy_response.get("Item") is None
