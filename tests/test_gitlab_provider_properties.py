"""Property-based tests for the gitlab-provider-support design.

Covers Properties 1-5 and 7-19 from the gitlab-provider-support design.
These properties do not need the populated-table fixture shape used by
`tests/test_git_mapping_properties.py` (Properties 6, 22, 23, 24, 25),
which rebuilds a mocked DynamoDB table per Hypothesis example — hence the
split into a separate module.
"""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from handlers.agent_correlation_handler import resolve_token_availability
from git_shared.git_providers import SSM_TOKEN_PATH_PREFIX


class _ParameterNotFound(Exception):
    """Stand-in for the boto3 SSM client's generated exception class."""


class _FakeSsmExceptions:
    """Mimics the ``client.exceptions`` namespace boto3 SSM clients expose."""

    ParameterNotFound = _ParameterNotFound


class _FakeSsmClient:
    """Fake SSM client whose ``get_parameter`` is driven by a caller-supplied
    ``{repoId: has_token}`` map, recording every call's ``Name`` kwarg.

    This avoids moto/`mock_aws()` entirely — the property under test is the
    PARTITION LOGIC in `resolve_token_availability`, not real AWS behavior,
    so a hand-rolled fake is simpler and faster.
    """

    exceptions = _FakeSsmExceptions

    def __init__(self, token_store: dict[str, bool]):
        self._token_store = token_store
        self.calls: list[str] = []

    def get_parameter(self, Name: str, WithDecryption: bool = False):
        self.calls.append(Name)
        repo_id = Name[len(f"{SSM_TOKEN_PATH_PREFIX}/") :]
        if self._token_store.get(repo_id, False):
            return {"Parameter": {"Name": Name, "Value": "irrelevant"}}
        raise self.exceptions.ParameterNotFound()


_REPO_ID_CHARS = st.text(alphabet="0123456789abcdef", min_size=8, max_size=8)

_DESCRIPTOR_STRATEGY = st.builds(
    lambda repo_id, provider: {
        "repoId": repo_id,
        "provider": provider,
        "gitUsername": f"user-{repo_id}",
    },
    repo_id=_REPO_ID_CHARS,
    provider=st.sampled_from(["github", "gitlab"]),
)


# Feature: gitlab-provider-support, Property 7: Repository-scoped token resolution
class TestProperty7RepositoryScopedTokenResolution:
    """Property 7: the token resolved for every repository is exactly the
    value stored under that repository's own `repoId` — never a value
    belonging to another repository (same or different provider), and the
    SSM lookup is keyed strictly on `repoId`.

    Not optional: handing the wrong provider's token to a tool produces an
    auth failure that looks like a user configuration problem, not a bug.

    Validates: Requirements 3.1, 3.2
    """

    @given(
        entries=st.lists(
            st.tuples(_DESCRIPTOR_STRATEGY, st.booleans()),
            min_size=0,
            max_size=10,
            unique_by=lambda entry: entry[0]["repoId"],
        )
    )
    @settings(max_examples=20)
    def test_token_availability_is_scoped_to_each_descriptors_own_repo_id(
        self, entries
    ):
        descriptors = [descriptor for descriptor, _has_token in entries]
        token_store = {
            descriptor["repoId"]: has_token for descriptor, has_token in entries
        }

        fake_client = _FakeSsmClient(token_store)

        available, missing = resolve_token_availability(
            descriptors, ssm_client=fake_client
        )

        # 1. Total partition — every descriptor lands in exactly one of the
        # two lists, none lost, none duplicated, none in both.
        available_ids = [d["repoId"] for d in available]
        missing_ids = [d["repoId"] for d in missing]
        assert len(available_ids) + len(missing_ids) == len(descriptors)
        assert set(available_ids).isdisjoint(set(missing_ids))
        assert set(available_ids) | set(missing_ids) == {
            d["repoId"] for d in descriptors
        }

        # 2. Repository-scoped decision: availability depends only on this
        # repoId's own entry in the fake store, never on whether some other
        # repoId (same or different provider) has a token. Since repoIds
        # are unique per generated example, this directly checks that each
        # descriptor's fate matches its own has_token flag with no
        # cross-repository or cross-provider leakage.
        for descriptor in descriptors:
            repo_id = descriptor["repoId"]
            expected_available = token_store[repo_id]
            if expected_available:
                assert repo_id in available_ids
                assert repo_id not in missing_ids
            else:
                assert repo_id in missing_ids
                assert repo_id not in available_ids

        # 3. The SSM parameter name constructed for each call is exactly
        # f"{SSM_TOKEN_PATH_PREFIX}/{repoId}" for that descriptor's own
        # repoId — proves the lookup is keyed on repoId, not on provider or
        # any other identifier.
        assert len(fake_client.calls) == len(descriptors)
        expected_names = {
            f"{SSM_TOKEN_PATH_PREFIX}/{descriptor['repoId']}"
            for descriptor in descriptors
        }
        assert set(fake_client.calls) == expected_names


from git_shared.git_url_parser import (
    build_repo_url,
    normalize_repo_url,
    parse_repo_url,
)

# A curated list of hostile inputs that are shaped like URLs (or
# URL-adjacent) but exercise corners `st.text()` is unlikely to hit on its
# own: scp-style remotes, IPv6 literals, a host with no path at all,
# embedded control/null bytes, and non-ASCII path segments.
_HOSTILE_URL_EXAMPLES = [
    "",
    " ",
    "\t\n",
    "git@host:path",
    "git@github.com:owner/repo.git",
    "ssh://git@host.example.com/owner/repo.git",
    "https://[::1]/repo",
    "https://[::1]:8443/group/project",
    "https://example.com",
    "https://example.com/",
    "http://",
    "https://",
    "not a url at all",
    "https://example.com/\x00/repo",
    "https://exa\x00mple.com/repo",
    "https://example.com/repo\x00",
    "\x00\x01\x02\x03",
    "https://例え.テスト/リポジトリ/プロジェクト",
    "https://example.com/owner/repo?query=1&other=2#fragment",
    "https://user:pass@example.com/owner/repo",
    "https://example.com:99999/owner/repo",
    "https://example.com:-1/owner/repo",
    "file:///etc/passwd",
    "//example.com/owner/repo",
    "https:///owner/repo",
    "https://example.com/owner/repo/",
    "https://example.com/owner/repo.git",
    None,  # not a str at all — exercises the isinstance guard
    123,
    3.14,
    [],
    {},
]

_url_strategy = st.one_of(
    st.text(),
    st.sampled_from(_HOSTILE_URL_EXAMPLES),
)

_provider_strategy = st.one_of(
    st.sampled_from(["github", "gitlab"]),
    st.text(),
    st.none(),
)

_location_strategy = st.dictionaries(
    keys=st.sampled_from(["owner", "repo", "baseUrl", "projectPath"]),
    values=st.one_of(st.text(), st.none()),
    max_size=4,
)


# Feature: gitlab-provider-support, Property 2: URL parser totality
class TestProperty2UrlParserTotality:
    """Property 2: for any string whatsoever — including the empty string,
    whitespace, control characters, scp-style `git@host:path` forms, IPv6
    literals, hosts with no path, and arbitrary Unicode — `parse_repo_url`
    (and its siblings `normalize_repo_url` / `build_repo_url`) terminate
    without raising and return either a well-formed result or `None`.

    Validates: Requirements 4.5
    """

    @given(url=_url_strategy)
    @settings(max_examples=20)
    def test_normalize_repo_url_never_raises(self, url):
        result = normalize_repo_url(url)
        assert result is None or isinstance(result, str)

    @given(provider=_provider_strategy, url=_url_strategy)
    @settings(max_examples=20)
    def test_parse_repo_url_never_raises(self, provider, url):
        result = parse_repo_url(provider, url)
        if result is None:
            return
        assert isinstance(result, dict)
        if provider == "github":
            assert set(result.keys()) == {"owner", "repo"}
        elif provider == "gitlab":
            assert set(result.keys()) == {"baseUrl", "projectPath"}
        else:
            # Any result for an unsupported provider would itself be a
            # contract violation — parse_repo_url must return None.
            raise AssertionError(
                f"parse_repo_url returned a non-None result for an "
                f"unsupported provider: {provider!r} -> {result!r}"
            )

    @given(provider=_provider_strategy, location=_location_strategy)
    @settings(max_examples=20)
    def test_build_repo_url_never_raises(self, provider, location):
        result = build_repo_url(provider, location)
        assert result is None or isinstance(result, str)


from git_shared.git_url_parser import build_repo_url, normalize_repo_url, parse_repo_url

_URL_LABEL_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"

_HOST_LABEL_STRATEGY = st.text(alphabet=_URL_LABEL_CHARS, min_size=1, max_size=8)

_HOST_STRATEGY = st.lists(_HOST_LABEL_STRATEGY, min_size=1, max_size=3).map(
    ".".join
)

_PATH_SEGMENT_STRATEGY = st.text(
    alphabet=_URL_LABEL_CHARS + "-_", min_size=1, max_size=10
)

_PORT_STRATEGY = st.one_of(st.none(), st.integers(min_value=1, max_value=65535))


def _compose_repo_url(scheme, host, port, segments, git_suffix, trailing_slash):
    """Build a repository URL string from its constituent parts.

    Mirrors the shapes normalize_repo_url is documented to accept: an
    http(s) scheme, an optional non-standard port, 2-6 path segments, and
    an optional trailing `.git` and/or trailing slash.
    """
    netloc = host if port is None else f"{host}:{port}"
    path = "/" + "/".join(segments)
    if git_suffix:
        path += ".git"
    if trailing_slash:
        path += "/"
    return f"{scheme}://{netloc}{path}"


# Composed URL parts for the general round-trip property: any scheme, any
# host, an optional port (standard or not), 2-6 segments, and the two
# optional decorations. Composing from parts — rather than sampling free
# text — is what reliably produces subgroup-depth and non-standard-port
# cases instead of relying on chance.
_GENERAL_URL_PARTS_STRATEGY = st.builds(
    lambda scheme, host, port, segments, git_suffix, trailing_slash: (
        segments,
        _compose_repo_url(scheme, host, port, segments, git_suffix, trailing_slash),
    ),
    scheme=st.sampled_from(["http", "https"]),
    host=_HOST_STRATEGY,
    port=_PORT_STRATEGY,
    segments=st.lists(_PATH_SEGMENT_STRATEGY, min_size=2, max_size=6),
    git_suffix=st.booleans(),
    trailing_slash=st.booleans(),
)

# GitHub-specific parts fixed to a github.com/https origin with exactly two
# path segments — the shape for which build_repo_url's hardcoded
# https://github.com host can reproduce the normalized original exactly,
# since GitHub locations carry no host of their own.
_GITHUB_EXACT_URL_PARTS_STRATEGY = st.builds(
    lambda segments, git_suffix, trailing_slash: (
        segments,
        _compose_repo_url(
            "https", "github.com", None, segments, git_suffix, trailing_slash
        ),
    ),
    segments=st.lists(_PATH_SEGMENT_STRATEGY, min_size=2, max_size=2),
    git_suffix=st.booleans(),
    trailing_slash=st.booleans(),
)


# Feature: gitlab-provider-support, Property 1: Repository URL round trip and normalization idempotence
class TestProperty1RepositoryUrlRoundTripAndNormalizationIdempotence:
    """Property 1: for any well-formed repository URL, parsing it for its
    provider and reconstructing it from the extracted location parameters
    round-trips back to the same location on re-parse, and normalizing an
    already-normalized URL returns it unchanged.

    Validates: Requirements 4.1, 4.2, 4.3, 4.6
    """

    @given(
        provider=st.sampled_from(["github", "gitlab"]),
        parts=_GENERAL_URL_PARTS_STRATEGY,
    )
    @settings(max_examples=20)
    def test_parse_build_reparse_round_trip_is_idempotent(self, provider, parts):
        _segments, url = parts

        normalized = normalize_repo_url(url)
        assert normalized is not None

        # Normalizing an already-normalized URL returns it unchanged.
        assert normalize_repo_url(normalized) == normalized

        location = parse_repo_url(provider, url)
        assert location is not None

        rebuilt = build_repo_url(provider, location)
        assert rebuilt is not None

        rebuilt_normalized = normalize_repo_url(rebuilt)
        assert rebuilt_normalized is not None

        # Idempotence: re-parsing the round-tripped URL yields exactly the
        # same location parameters as the original parse — the same
        # owner/repo for GitHub, or the same baseUrl/projectPath for
        # GitLab, regardless of subgroup depth or the original port.
        reparsed = parse_repo_url(provider, rebuilt_normalized)
        assert reparsed == location

    @given(parts=_GITHUB_EXACT_URL_PARTS_STRATEGY)
    @settings(max_examples=20)
    def test_github_two_segment_round_trip_reconstructs_normalized_original(
        self, parts
    ):
        _segments, url = parts

        normalized = normalize_repo_url(url)
        assert normalized is not None

        location = parse_repo_url("github", url)
        assert location is not None

        rebuilt = build_repo_url("github", location)
        assert rebuilt is not None

        rebuilt_normalized = normalize_repo_url(rebuilt)

        # For GitHub with exactly two path segments on a github.com/https
        # origin, the round trip reconstructs the normalized original
        # exactly — the one shape where build_repo_url's hardcoded host
        # matches the input's own host.
        assert rebuilt_normalized == normalized


# ---------------------------------------------------------------------------
# Property 5: Repository configuration round trip and secret non-disclosure
# ---------------------------------------------------------------------------

import boto3
from moto import mock_aws

from backend.handlers.git_repo_handler import handle_create_repo, handle_list_repos


_REPO_TABLE_NAME = "TestAnalyticsTablePropFive"

# Printable, non-whitespace characters so `.strip()` in the handler never
# changes the value — this keeps the round-trip comparison exact instead of
# having to re-derive what stripping would have done.
_NO_WHITESPACE_PRINTABLE = st.characters(
    min_codepoint=33, max_codepoint=126, blacklist_characters="\\"
)

_REPO_NAME_STRATEGY = st.text(
    alphabet=_NO_WHITESPACE_PRINTABLE, min_size=1, max_size=30
)

_ACCESS_TOKEN_STRATEGY = st.text(
    alphabet=_NO_WHITESPACE_PRINTABLE, min_size=10, max_size=500
)

_HOST_LABEL_STRATEGY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=10
)

_PATH_SEGMENT_STRATEGY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=12
)


@st.composite
def _repo_url_strategy(draw):
    """Compose a repository URL from parts: scheme, host labels, an
    optional non-standard port, and 1-3 path segments — reusing the same
    part-composition approach a URL round-trip property needs, rather than
    sampling free text that would rarely produce a parseable, valid URL.
    """
    scheme = draw(st.sampled_from(["http", "https"]))
    host_labels = draw(
        st.lists(_HOST_LABEL_STRATEGY, min_size=2, max_size=4)
    )
    host = ".".join(host_labels)
    port = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=65535)))
    port_str = f":{port}" if port is not None else ""
    path_segments = draw(
        st.lists(_PATH_SEGMENT_STRATEGY, min_size=1, max_size=3)
    )
    path = "/".join(path_segments)
    return f"{scheme}://{host}{port_str}/{path}"


def _create_repo_table(resource):
    resource.create_table(
        TableName=_REPO_TABLE_NAME,
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


# Feature: gitlab-provider-support, Property 5: Repository configuration round trip and secret non-disclosure
class TestProperty5RepositoryConfigurationRoundTrip:
    """Property 5: a repository configuration created via handle_create_repo
    round-trips through handle_list_repos with name/url/provider intact,
    and the submitted access token never appears anywhere in either
    response — not in the creation response, not in the list response, and
    not exposed via an `ssmTokenPath`, `accessToken`, or `token` key.

    Validates: Requirements 1.1, 1.2, 1.5
    """

    @given(
        name=_REPO_NAME_STRATEGY,
        url=_repo_url_strategy(),
        provider=st.sampled_from(["github", "gitlab"]),
        access_token=_ACCESS_TOKEN_STRATEGY,
    )
    @settings(max_examples=20, deadline=None)
    def test_repo_config_round_trips_without_disclosing_the_token(
        self, name, url, provider, access_token
    ):
        import os
        from hypothesis import assume

        # `name` and `access_token` are drawn from the same printable
        # alphabet, so Hypothesis can (rarely) generate them as literally
        # equal strings, e.g. both "0000000000". That is not a secret
        # disclosure — the token would legitimately appear via the `name`
        # field the caller submitted, not via any secret-carrying field —
        # so it is excluded rather than asserted against. Same reasoning
        # for the token coincidentally appearing as a substring of `url`.
        assume(access_token != name)
        assume(access_token not in url)
        # Same reasoning again for the token coincidentally appearing as a
        # substring of a fixed structural/key literal in the response
        # shape itself (e.g. access_token="repositori" is a substring of
        # the JSON key "repositories") — that is a false positive from a
        # blanket str()-based containment check, not a secret disclosure,
        # since none of these literals ever carry the token's value.
        _STRUCTURAL_LITERALS = (
            "repositories repoId name url provider tokenConfigured status "
            "lastSyncAt createdAt error message _status_code"
        )
        assume(access_token not in _STRUCTURAL_LITERALS)

        with mock_aws():
            os.environ["ANALYTICS_TABLE"] = _REPO_TABLE_NAME
            resource = boto3.resource("dynamodb", region_name="us-east-1")
            _create_repo_table(resource)
            ssm_client = boto3.client("ssm", region_name="us-east-1")

            body = {
                "name": name,
                "url": url,
                "provider": provider,
                "accessToken": access_token,
            }
            claims = {"userId": "admin-property-test"}

            create_result = handle_create_repo(
                body,
                claims,
                dynamodb_resource=resource,
                ssm_client=ssm_client,
            )

            assert create_result["_status_code"] == 201

            # Secret non-disclosure in the creation response: the raw token
            # value must not appear anywhere in the returned dict.
            assert access_token not in str(create_result)

            repo_id = create_result["repoId"]

            list_result = handle_list_repos(dynamodb_resource=resource)
            repositories = list_result["repositories"]

            matching = [r for r in repositories if r["repoId"] == repo_id]
            assert len(matching) == 1
            listed = matching[0]

            # Round trip: name, url, and provider submitted at creation
            # come back unchanged (the handler strips name/url and
            # lowercases provider, and the composed inputs are already
            # stripped/lowercase-stable by construction).
            assert listed["name"] == name
            assert listed["url"] == url
            assert listed["provider"] == provider.lower()

            # Secret non-disclosure in the list response.
            assert "ssmTokenPath" not in listed
            assert "accessToken" not in listed
            assert "token" not in listed
            assert access_token not in str(list_result)


# ----------------------------------------------------------------------
# Property 4: Provider validation is exactly the supported set
# ----------------------------------------------------------------------

import os

import boto3
from moto import mock_aws

from backend.handlers.git_repo_handler import handle_create_repo
from backend.handlers.git_mapping_handler import handle_create_mapping
from git_shared.git_providers import SUPPORTED_PROVIDERS


_PROPERTY4_TABLE_NAME = "TestAnalyticsTable"


def _property4_create_table(resource):
    """Create the mocked Analytics_Table with the standard PK/SK schema."""
    resource.create_table(
        TableName=_PROPERTY4_TABLE_NAME,
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


def _property4_supported_provider_strategy():
    """Draw a provider string whose `.strip().lower()` form is a member of
    SUPPORTED_PROVIDERS — mixing case variants and surrounding whitespace.
    """
    return st.sampled_from(sorted(SUPPORTED_PROVIDERS)).flatmap(
        lambda base: st.builds(
            lambda casing, leading_ws, trailing_ws: leading_ws
            + casing(base)
            + trailing_ws,
            casing=st.sampled_from(
                [str.lower, str.upper, str.title, str.capitalize]
            ),
            leading_ws=st.sampled_from(["", " ", "  ", "\t"]),
            trailing_ws=st.sampled_from(["", " ", "  ", "\t"]),
        )
    )


def _property4_unsupported_provider_strategy():
    """Draw a provider string whose `.strip().lower()` form is NOT a member
    of SUPPORTED_PROVIDERS — arbitrary text, empty string, whitespace-only,
    and case variations of names that are deliberately not supported.
    """
    supported_lower = {p.lower() for p in SUPPORTED_PROVIDERS}

    arbitrary_text = st.text(max_size=30).filter(
        lambda s: s.strip().lower() not in supported_lower
    )

    known_unsupported_names = st.sampled_from(
        ["bitbucket", "codecommit", "svn", "perforce", "git"]
    )
    cased_unsupported = known_unsupported_names.flatmap(
        lambda base: st.builds(
            lambda casing, leading_ws, trailing_ws: leading_ws
            + casing(base)
            + trailing_ws,
            casing=st.sampled_from(
                [str.lower, str.upper, str.title, str.capitalize]
            ),
            leading_ws=st.sampled_from(["", " ", "  ", "\t"]),
            trailing_ws=st.sampled_from(["", " ", "  ", "\t"]),
        )
    )

    return st.one_of(
        arbitrary_text,
        st.just(""),
        st.sampled_from([" ", "  ", "\t", "\n", "   \t  "]),
        cased_unsupported,
    )


def _property4_claims():
    return {"userId": "admin-1", "groups": ["Admins"]}


# Feature: gitlab-provider-support, Property 4: Provider validation is exactly the supported set
class TestProperty4ProviderValidationIsExactlyTheSupportedSet:
    """Property 4: for any provider string, both the repository creation
    handler and the mapping creation handler accept it if and only if its
    lowercased (and stripped) form is a member of SUPPORTED_PROVIDERS;
    every rejection returns HTTP 400 with error ValidationError and a
    message naming every supported provider.

    Each handler is exercised with an otherwise-valid request body, so the
    provider check is isolated from the other validation branches (missing
    fields, invalid URL, unknown user, etc.).

    Validates: Requirements 1.3, 2.2
    """

    @given(provider=_property4_supported_provider_strategy())
    @settings(max_examples=20, deadline=None)
    def test_repo_handler_accepts_supported_providers_regardless_of_case_or_whitespace(
        self, provider
    ):
        with mock_aws():
            os.environ["ANALYTICS_TABLE"] = _PROPERTY4_TABLE_NAME
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _property4_create_table(ddb)
            ssm = boto3.client("ssm", region_name="us-east-1")

            body = {
                "name": "my-repo",
                "url": "https://example.com/org/repo",
                "provider": provider,
                "accessToken": "a-valid-access-token-1234",
            }

            result = handle_create_repo(
                body,
                _property4_claims(),
                dynamodb_resource=ddb,
                ssm_client=ssm,
            )

            assert result.get("_status_code") == 201
            assert result.get("provider") == provider.strip().lower()

    @given(provider=_property4_unsupported_provider_strategy())
    @settings(max_examples=20, deadline=None)
    def test_repo_handler_rejects_unsupported_providers_with_message_listing_supported_set(
        self, provider
    ):
        with mock_aws():
            os.environ["ANALYTICS_TABLE"] = _PROPERTY4_TABLE_NAME
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _property4_create_table(ddb)
            ssm = boto3.client("ssm", region_name="us-east-1")

            body = {
                "name": "my-repo",
                "url": "https://example.com/org/repo",
                "provider": provider,
                "accessToken": "a-valid-access-token-1234",
            }

            result = handle_create_repo(
                body,
                _property4_claims(),
                dynamodb_resource=ddb,
                ssm_client=ssm,
            )

            # Always a 400 ValidationError, whatever the branch.
            assert result.get("_status_code") == 400
            assert result.get("error") == "ValidationError"

            # A provider that is empty (or entirely whitespace, once
            # stripped) is caught by the earlier "missing required
            # fields" branch rather than the provider-specific check, so
            # its message does not name the supported providers — that
            # message is about field presence, not provider validity, and
            # is exercised by the handler's own "missing fields" tests.
            # The provider-listing message is only guaranteed when the
            # provider check itself is what rejects the request.
            if provider.strip():
                message_lower = result.get("message", "").lower()
                for supported in SUPPORTED_PROVIDERS:
                    assert supported.lower() in message_lower

    @given(provider=_property4_supported_provider_strategy())
    @settings(max_examples=20, deadline=None)
    def test_mapping_handler_accepts_supported_providers_regardless_of_case_or_whitespace(
        self, provider
    ):
        with mock_aws():
            os.environ["ANALYTICS_TABLE"] = _PROPERTY4_TABLE_NAME
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _property4_create_table(ddb)

            # The mapping handler validates that the Kiro user exists via a
            # query on USER#{userId}; seed a minimal item so that branch
            # passes and the provider check is isolated.
            table = ddb.Table(_PROPERTY4_TABLE_NAME)
            table.put_item(
                Item={"PK": "USER#user-1", "SK": "STATS#DAILY#2024-01-01"}
            )

            body = {
                "userId": "user-1",
                "provider": provider,
                "gitUsername": "octocat",
            }

            result = handle_create_mapping(
                body, _property4_claims(), dynamodb_resource=ddb
            )

            assert result.get("_status_code") == 201
            assert result.get("provider") == provider.strip().lower()

    @given(provider=_property4_unsupported_provider_strategy())
    @settings(max_examples=20, deadline=None)
    def test_mapping_handler_rejects_unsupported_providers_with_message_listing_supported_set(
        self, provider
    ):
        with mock_aws():
            os.environ["ANALYTICS_TABLE"] = _PROPERTY4_TABLE_NAME
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _property4_create_table(ddb)

            table = ddb.Table(_PROPERTY4_TABLE_NAME)
            table.put_item(
                Item={"PK": "USER#user-1", "SK": "STATS#DAILY#2024-01-01"}
            )

            body = {
                "userId": "user-1",
                "provider": provider,
                "gitUsername": "octocat",
            }

            result = handle_create_mapping(
                body, _property4_claims(), dynamodb_resource=ddb
            )

            # Always a 400 ValidationError, whatever the branch.
            assert result.get("_status_code") == 400
            assert result.get("error") == "ValidationError"

            # Same precedence caveat as the repo handler: an empty (or
            # whitespace-only) provider is caught by the "missing
            # required fields" branch, whose message does not name the
            # supported providers.
            if provider.strip():
                message_lower = result.get("message", "").lower()
                for supported in SUPPORTED_PROVIDERS:
                    assert supported.lower() in message_lower


# ----------------------------------------------------------------------
# Property 9: Token-missing slug selection totality and determinism
# ----------------------------------------------------------------------

import random

from handlers.agent_correlation_handler import select_token_missing_slug
from git_shared.git_providers import PROVIDER_ORDER, TOKEN_MISSING_SLUG

_MISSING_DESCRIPTOR_STRATEGY = st.builds(
    lambda provider: {"provider": provider},
    provider=st.sampled_from(sorted(SUPPORTED_PROVIDERS)),
)


# Feature: gitlab-provider-support, Property 9: Token-missing slug selection totality and determinism
class TestProperty9TokenMissingSlugSelectionTotalityAndDeterminism:
    """Property 9: for any non-empty list of missing-token descriptors,
    `select_token_missing_slug` always returns a valid `TOKEN_MISSING_SLUG`
    value, never raises, and its result depends only on the multiset of
    providers present in `missing` — not on the list's order. The provider
    with the strictly greatest count of missing descriptors wins; ties
    break by `PROVIDER_ORDER` (`"github"` before `"gitlab"`).

    Validates: Requirements 3.3
    """

    @given(
        missing=st.lists(_MISSING_DESCRIPTOR_STRATEGY, min_size=1, max_size=20)
    )
    @settings(max_examples=20)
    def test_totality_never_raises_and_returns_a_valid_slug(self, missing):
        result = select_token_missing_slug(missing)

        assert result is not None
        assert isinstance(result, str)
        assert result in TOKEN_MISSING_SLUG.values()

    @given(
        missing=st.lists(_MISSING_DESCRIPTOR_STRATEGY, min_size=1, max_size=20),
        seed=st.integers(min_value=0, max_value=2**32 - 1),
    )
    @settings(max_examples=20)
    def test_determinism_is_independent_of_input_order(self, missing, seed):
        rng = random.Random(seed)
        shuffled = list(missing)
        rng.shuffle(shuffled)

        # Calling twice with the same (unshuffled) input is stable.
        assert select_token_missing_slug(missing) == select_token_missing_slug(
            missing
        )

        # A shuffled/reordered copy of the same input yields the same
        # result — the decision depends on the multiset of providers, not
        # on list order.
        assert select_token_missing_slug(missing) == select_token_missing_slug(
            shuffled
        )

    @given(
        missing=st.lists(_MISSING_DESCRIPTOR_STRATEGY, min_size=1, max_size=20)
    )
    @settings(max_examples=20)
    def test_most_affected_provider_wins_with_provider_order_tiebreak(
        self, missing
    ):
        counts: dict[str, int] = {}
        for descriptor in missing:
            provider = descriptor["provider"]
            counts[provider] = counts.get(provider, 0) + 1

        max_count = max(counts.values())

        # Among the providers tied for the max count, PROVIDER_ORDER's
        # first entry is the expected winner.
        expected_winner = next(
            provider
            for provider in PROVIDER_ORDER
            if counts.get(provider, 0) == max_count
        )

        result = select_token_missing_slug(missing)
        assert result == TOKEN_MISSING_SLUG[expected_winner]

        # The returned slug's provider never has a strictly smaller count
        # than any other provider present in `missing` — i.e. it is
        # genuinely "most affected", not merely PROVIDER_ORDER's first
        # entry regardless of counts.
        winning_provider = next(
            provider
            for provider, slug in TOKEN_MISSING_SLUG.items()
            if slug == result
        )
        for provider, count in counts.items():
            assert counts[winning_provider] >= count


# ----------------------------------------------------------------------
# Property 19: Correlation status slug closure and absence of prose
# ----------------------------------------------------------------------

import json

from handlers.agent_correlation_handler import (
    CORRELATION_STATUS_SLUGS,
    _format_response,
)

# The wider set of status values the handler's own docstring documents as
# legitimate: every terminal CorrelationStatusSlug, plus the two in-flight
# / success values that are valid `status` inputs to `_format_response`
# but are not members of the Literal union ("processing" is transient,
# "ready" is the success default). `None` is included to exercise the
# "ready" default path explicitly.
_PROPERTY19_STATUS_VALUE_STRATEGY = st.one_of(
    st.sampled_from(sorted(CORRELATION_STATUS_SLUGS)),
    st.just("processing"),
    st.just("ready"),
    st.none(),
)

# A fixed, distinctive user id rather than a generated one — it keeps the
# "message never leaks into the response" assertion meaningful: the only
# response fields that could ever coincidentally contain arbitrary text
# are `userId` and `status`, both supplied independently of `message`, so
# fixing `userId` removes one source of accidental (non-leak) collision.
_PROPERTY19_USER_ID = "prop19-fixed-user-id"

_PROPERTY19_ANALYSIS = {"period": {"startDate": "2024-01-01", "endDate": "2024-01-07"}}


# Feature: gitlab-provider-support, Property 19: Correlation status slug closure and absence of prose
class TestProperty19CorrelationStatusSlugClosureAndAbsenceOfProse:
    """Property 19: for any status value drawn from `CORRELATION_STATUS_SLUGS`
    (or from the slightly wider set of valid non-slug status values —
    `"processing"` and `"ready"` — plus `None` for the success default),
    `_format_response` always returns a response whose `status` field is
    exactly the provided slug (or `"ready"` when `status` is `None`), and
    whose response body never contains the arbitrary `message` text passed
    in. The response body only ever carries the machine-stable slug; the
    message is logged and dropped, never echoed back to the client.

    This holds for every member of `CORRELATION_STATUS_SLUGS` — not just a
    sample — since the status strategy is drawn directly from that
    frozenset via `st.sampled_from(sorted(...))`.

    Validates: Requirements 8.4, 8.6
    """

    @given(
        status=_PROPERTY19_STATUS_VALUE_STRATEGY,
        message=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=20)
    def test_status_slug_closure_and_message_never_appears_in_response_body(
        self, status, message
    ):
        status_str = status if status is not None else "ready"

        # Baseline: the response `_format_response` produces for this same
        # (userId, analysis, status) with NO message at all. Every byte in
        # this baseline is fixed scaffolding unrelated to `message` (the
        # user id, the status slug, the period dates, etc.). Comparing
        # against it — rather than guessing which literals might collide
        # (dates contain digits, `status_str` might contain letters that
        # also appear in `message`, etc.) — is what makes the "message
        # never leaks" assertion exact instead of approximate.
        baseline = _format_response(
            _PROPERTY19_USER_ID,
            _PROPERTY19_ANALYSIS,
            cached=False,
            status=status,
        )
        baseline_serialized = json.dumps(baseline, default=str)
        assume(message not in baseline_serialized)

        response = _format_response(
            _PROPERTY19_USER_ID,
            _PROPERTY19_ANALYSIS,
            cached=False,
            status=status,
            message=message,
        )

        # Closure: the response's status is exactly the provided slug, or
        # "ready" when status was None (the success default).
        assert response["status"] == status_str

        # Absence of prose: passing `message` produces byte-for-byte the
        # same response as passing no message at all — the message is
        # logged and dropped, never merged into any response field.
        assert response == baseline

        serialized = json.dumps(response, default=str)
        assert message not in serialized

    @given(status=st.sampled_from(sorted(CORRELATION_STATUS_SLUGS)))
    @settings(max_examples=20)
    def test_totality_over_every_member_of_the_slug_set(self, status):
        # Totality: every member of CORRELATION_STATUS_SLUGS — not just a
        # sample — round-trips through `_format_response` as-is, with no
        # message argument at all (message is optional).
        response = _format_response(
            _PROPERTY19_USER_ID,
            _PROPERTY19_ANALYSIS,
            cached=False,
            status=status,
        )
        assert response["status"] == status
        assert response["status"] in CORRELATION_STATUS_SLUGS

    def test_closure_holds_for_every_slug_iterated_directly(self):
        # Iterate the frozenset directly (not via a Hypothesis strategy) so
        # the closure claim is checked against literally every member,
        # independent of Hypothesis's example budget for the property above.
        for status in CORRELATION_STATUS_SLUGS:
            response = _format_response(
                _PROPERTY19_USER_ID,
                _PROPERTY19_ANALYSIS,
                cached=False,
                status=status,
                message="some free-text operator message that must not leak",
            )
            assert response["status"] == status
            assert "leak" not in json.dumps(response, default=str)


# ----------------------------------------------------------------------
# Property 11: Descriptor and exclusion partition
# ----------------------------------------------------------------------

from hypothesis import assume

from handlers.agent_correlation_handler import build_repo_descriptors

_P11_KNOWN_UNSUPPORTED_PROVIDERS = ["bitbucket", "codecommit", "svn", "perforce"]

# URLs that `parse_repo_url` is guaranteed to return None for regardless of
# provider: no path segments at all, free text, an scp-style remote, and
# the empty string.
_P11_UNPARSEABLE_URLS = [
    "https://onlyhost.example.com",
    "https://onlyhost.example.com/",
    "not a url at all",
    "git@host.example.com:owner/repo.git",
    "",
]


def _p11_well_formed_url(provider: str, repo_id: str) -> str:
    """Build a URL `parse_repo_url` is guaranteed to parse for `provider`,
    using `repo_id` to keep values distinct across generated configs.
    """
    if provider == "github":
        return f"https://github.com/owner-{repo_id}/repo-{repo_id}"
    # Only "github" and "gitlab" are members of SUPPORTED_PROVIDERS today;
    # treat anything else as GitLab-shaped so this helper stays total.
    return f"https://gitlab.example.com/group-{repo_id}/project-{repo_id}"


@st.composite
def _p11_scenario_strategy(draw):
    """Draw a full (repo_configs, mappings) scenario that deliberately
    mixes all four outcomes `build_repo_descriptors` can produce: a config
    that resolves to a descriptor (supported provider + parseable URL +
    matching mapping), one excluded for an unsupported provider, one
    excluded for an unparseable URL, and one excluded for a missing
    mapping. A generator that only ever produced one category would make
    the partition claim vacuous, so one of each is guaranteed, plus a
    variable number of extra entries drawn from the same four categories
    on top.
    """
    supported = sorted(SUPPORTED_PROVIDERS)
    mapped_provider = draw(st.sampled_from(supported))
    unmapped_providers = [p for p in supported if p != mapped_provider]
    assume(len(unmapped_providers) >= 1)
    no_mapping_provider = unmapped_providers[0]

    base_categories = [
        "descriptor",
        "unsupported_provider",
        "unparseable_url",
        "no_mapping",
    ]
    extra_categories = draw(
        st.lists(st.sampled_from(base_categories), min_size=0, max_size=8)
    )
    all_categories = base_categories + extra_categories

    repo_ids = draw(
        st.lists(
            st.text(alphabet="0123456789abcdef", min_size=8, max_size=8),
            min_size=len(all_categories),
            max_size=len(all_categories),
            unique=True,
        )
    )

    repo_configs: list[dict] = []
    expected_reasons: dict[str, str | None] = {}

    for repo_id, category in zip(repo_ids, all_categories):
        if category == "descriptor":
            provider = mapped_provider
            url = _p11_well_formed_url(provider, repo_id)
            expected_reasons[repo_id] = None
        elif category == "unsupported_provider":
            provider = draw(st.sampled_from(_P11_KNOWN_UNSUPPORTED_PROVIDERS))
            url = _p11_well_formed_url("gitlab", repo_id)
            expected_reasons[repo_id] = "UNSUPPORTED_PROVIDER"
        elif category == "unparseable_url":
            provider = draw(st.sampled_from(supported))
            url = draw(st.sampled_from(_P11_UNPARSEABLE_URLS))
            expected_reasons[repo_id] = "UNPARSEABLE_URL"
        else:  # "no_mapping"
            provider = no_mapping_provider
            url = _p11_well_formed_url(provider, repo_id)
            expected_reasons[repo_id] = "NO_USER_MAPPING"

        repo_configs.append(
            {"PK": f"GITREPO#{repo_id}", "url": url, "provider": provider}
        )

    mappings = [{"provider": mapped_provider, "gitUsername": f"user-{mapped_provider}"}]

    return repo_configs, mappings, expected_reasons


# Feature: gitlab-provider-support, Property 11: Descriptor and exclusion partition
class TestProperty11DescriptorAndExclusionPartition:
    """Property 11: for any mix of repository configs — some with a
    supported provider, a parseable URL, and a matching user mapping; some
    with an unsupported provider; some with a parseable URL but no matching
    mapping for that provider; and some with a supported provider but an
    unparseable URL — every input config lands in exactly one of the
    descriptors list or the excluded list, matched by `repoId`. The two
    lists never overlap and never lose a config, every excluded entry's
    `reason` is one of the three known reason codes and correctly
    identifies why that specific config was excluded, and
    `len(descriptors) + len(excluded) == len(repo_configs)`.

    Validates: Requirements 7.3, 4.5
    """

    @given(scenario=_p11_scenario_strategy())
    @settings(max_examples=20)
    def test_every_config_lands_in_exactly_one_list_with_the_correct_reason(
        self, scenario
    ):
        repo_configs, mappings, expected_reasons = scenario

        descriptors, excluded = build_repo_descriptors(repo_configs, mappings)

        input_ids = {c["PK"].replace("GITREPO#", "") for c in repo_configs}
        descriptor_ids = [d["repoId"] for d in descriptors]
        excluded_ids = [e["repoId"] for e in excluded]

        # 1. Total partition: every input repoId appears in exactly one of
        # the two lists (matched by repoId) — no config lost, none
        # duplicated, none in both.
        assert len(set(descriptor_ids)) == len(descriptor_ids)
        assert len(set(excluded_ids)) == len(excluded_ids)
        assert set(descriptor_ids).isdisjoint(set(excluded_ids))
        assert set(descriptor_ids) | set(excluded_ids) == input_ids

        # 2. len(descriptors) + len(excluded) == len(repo_configs).
        assert len(descriptors) + len(excluded) == len(repo_configs)

        # 3. Every excluded entry's reason is one of the three known reason
        # codes, and it matches the specific reason this config was
        # constructed to trigger — e.g. a config built with an
        # unsupported provider is excluded specifically with
        # UNSUPPORTED_PROVIDER, not one of the other two.
        known_reasons = {
            "UNSUPPORTED_PROVIDER",
            "UNPARSEABLE_URL",
            "NO_USER_MAPPING",
        }
        excluded_by_id = {e["repoId"]: e for e in excluded}
        for repo_id, expected_reason in expected_reasons.items():
            if expected_reason is None:
                assert repo_id in descriptor_ids
                assert repo_id not in excluded_by_id
            else:
                assert repo_id in excluded_by_id
                actual_reason = excluded_by_id[repo_id]["reason"]
                assert actual_reason in known_reasons
                assert actual_reason == expected_reason


# ----------------------------------------------------------------------
# Property 10: Repository descriptor well-formedness and provider-matched
# username
# ----------------------------------------------------------------------

import json

from handlers.agent_correlation_handler import (
    build_repo_descriptors,
    resolve_usernames_by_provider,
)
from git_shared.git_providers import SUPPORTED_PROVIDERS as _P10_SUPPORTED_PROVIDERS

_P10_REPO_ID_STRATEGY = st.text(alphabet="0123456789abcdef", min_size=8, max_size=8)

_P10_HOST_LABEL_STRATEGY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8
)

_P10_PATH_SEGMENT_STRATEGY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=10
)

# Location fields a well-formed descriptor must carry for each provider —
# the check that a github descriptor never carries baseUrl/projectPath and
# a gitlab descriptor never carries owner/repo, per Property 10's "exactly
# the location keys defined for that provider and no others".
_P10_LOCATION_FIELDS = {
    "github": {"owner", "repo"},
    "gitlab": {"baseUrl", "projectPath"},
}

# Fields a descriptor must never carry, per DD-3: descriptors carry repoId
# only, never a token value or an SSM parameter path.
_P10_FORBIDDEN_FIELDS = {
    "token",
    "accessToken",
    "ssmTokenPath",
    "ssmParameterPath",
    "secret",
}


@st.composite
def _p10_repo_config_strategy(draw):
    """A repository config with a valid, parseable URL for its provider.

    Biasing every generated URL to be parseable (rather than sampling free
    text) keeps most examples inside the "descriptor actually produced"
    branch of build_repo_descriptors, which is what this property needs to
    say anything about descriptor shape — an all-excluded run would make
    the well-formedness assertions vacuously true.
    """
    provider = draw(st.sampled_from(sorted(_P10_SUPPORTED_PROVIDERS)))
    repo_id = draw(_P10_REPO_ID_STRATEGY)
    scheme = draw(st.sampled_from(["http", "https"]))
    host = ".".join(draw(st.lists(_P10_HOST_LABEL_STRATEGY, min_size=1, max_size=3)))
    port = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=65535)))
    port_str = f":{port}" if port is not None else ""

    # github needs exactly owner/repo (>= 2 segments is fine, parser takes
    # the last two); gitlab needs at least one segment and may have
    # subgroups.
    min_segments = 2 if provider == "github" else 1
    max_segments = 2 if provider == "github" else 4
    segments = draw(
        st.lists(
            _P10_PATH_SEGMENT_STRATEGY, min_size=min_segments, max_size=max_segments
        )
    )
    path = "/".join(segments)
    url = f"{scheme}://{host}{port_str}/{path}"

    return {
        "PK": f"GITREPO#{repo_id}",
        "provider": provider,
        "url": url,
    }


@st.composite
def _p10_mapping_strategy(draw):
    """A user-to-Git mapping whose gitUsername is prefixed by its own
    provider name, so a github username and a gitlab username can never
    collide by chance — a cross-provider leak (Property 10's leading
    concern) would otherwise sometimes go undetected if both providers
    happened to draw the same username string.
    """
    provider = draw(st.sampled_from(sorted(_P10_SUPPORTED_PROVIDERS)))
    suffix = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_.",
            min_size=1,
            max_size=16,
        )
    )
    mapping = {"provider": provider, "gitUsername": f"{provider}-{suffix}"}
    created_at = draw(
        st.one_of(
            st.none(),
            st.sampled_from(["2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z"]),
        )
    )
    if created_at is not None:
        mapping["createdAt"] = created_at
    return mapping


# Feature: gitlab-provider-support, Property 10: Repository descriptor well-formedness and provider-matched username
class TestProperty10RepositoryDescriptorWellFormedness:
    """Property 10: for any set of repository configurations and any set of
    user mappings, every descriptor emitted by `build_repo_descriptors` is
    well-formed (repoId populated, provider in SUPPORTED_PROVIDERS, exactly
    the location keys defined for that provider and no others), carries a
    `gitUsername` matching the username `resolve_usernames_by_provider`
    resolves for that descriptor's own provider — never a cross-provider
    value — and never carries a token value or an SSM parameter store path
    field (DD-3).

    Validates: Requirements 7.1, 7.2
    """

    @given(
        repo_configs=st.lists(
            _p10_repo_config_strategy(),
            min_size=0,
            max_size=8,
            unique_by=lambda config: config["PK"],
        ),
        mappings=st.lists(_p10_mapping_strategy(), min_size=0, max_size=6),
    )
    @settings(max_examples=20)
    def test_descriptor_well_formedness_and_provider_matched_username(
        self, repo_configs, mappings
    ):
        descriptors, _excluded = build_repo_descriptors(repo_configs, mappings)
        usernames_by_provider = resolve_usernames_by_provider(mappings)

        for descriptor in descriptors:
            provider = descriptor.get("provider")

            # 1 & 2. Well-formedness: repoId populated, provider is a
            # supported provider, and every provider-appropriate location
            # field is present and non-empty.
            assert descriptor.get("repoId")
            assert provider in _P10_SUPPORTED_PROVIDERS

            expected_location_fields = _P10_LOCATION_FIELDS[provider]
            other_providers_fields = set().union(
                *(
                    fields
                    for other_provider, fields in _P10_LOCATION_FIELDS.items()
                    if other_provider != provider
                )
            )
            for field in expected_location_fields:
                assert descriptor.get(field), (
                    f"descriptor for provider {provider!r} missing "
                    f"required location field {field!r}: {descriptor!r}"
                )
            # No other provider's location fields leak into this
            # descriptor — a gitlab descriptor never carries owner/repo
            # and a github descriptor never carries baseUrl/projectPath.
            for field in other_providers_fields:
                assert field not in descriptor, (
                    f"descriptor for provider {provider!r} unexpectedly "
                    f"carries field {field!r} belonging to another "
                    f"provider: {descriptor!r}"
                )

            # 3. gitUsername matches the username resolved for this
            # descriptor's OWN provider — never a value belonging to a
            # different provider's mapping.
            assert descriptor.get("gitUsername") == usernames_by_provider.get(
                provider
            )

            # 4. Per DD-3, no descriptor ever carries a token value or an
            # SSM parameter path field.
            for forbidden in _P10_FORBIDDEN_FIELDS:
                assert forbidden not in descriptor, (
                    f"descriptor unexpectedly carries forbidden field "
                    f"{forbidden!r}: {descriptor!r}"
                )

            # Bonus well-formedness check from the design's Property 10:
            # every descriptor survives a JSON encode-decode round trip
            # unchanged, so it is safe to forward verbatim into the agent
            # invocation payload (component 5).
            assert json.loads(json.dumps(descriptor)) == descriptor


# ----------------------------------------------------------------------
# Property 12: Agent invocation payload round trip
# ----------------------------------------------------------------------

import json
import os
from unittest.mock import MagicMock, patch

from handlers.correlation_worker import _invoke_agent

# JSON-safe leaf values. NaN/Infinity are excluded: json.dumps emits the
# non-standard "NaN"/"Infinity" literals for them and json.loads parses
# those back to float values that are not equal to themselves (nan != nan),
# which would make the round-trip equality assertion fail for reasons
# unrelated to the property under test.
_P12_JSON_LEAF_STRATEGY = st.one_of(
    st.text(max_size=20),
    st.integers(min_value=-10_000, max_value=10_000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.booleans(),
    st.none(),
)

# A repository descriptor with NO fixed shape: arbitrary string keys
# (deliberately not limited to "repoId"/"provider"/location fields) mapped
# to arbitrary JSON-safe leaves or short lists of leaves. The point of
# "forwarded verbatim" is that `_invoke_agent` never inspects or validates
# descriptor shape, so the generator must not bake in an assumed shape
# either — otherwise the property would only demonstrate the round trip
# for shapes the test author happened to imagine.
_P12_ARBITRARY_DESCRIPTOR_STRATEGY = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=st.one_of(
        _P12_JSON_LEAF_STRATEGY,
        st.lists(_P12_JSON_LEAF_STRATEGY, max_size=5),
    ),
    min_size=0,
    max_size=8,
)

_P12_ARBITRARY_REPOS_STRATEGY = st.lists(
    _P12_ARBITRARY_DESCRIPTOR_STRATEGY, min_size=0, max_size=10
)

_P12_VALID_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:sa-east-1:123456789012:runtime/TestCorrelationAgent"
)


class _P12FakeAgentCoreClient:
    """Fake `bedrock-agentcore` client capturing the raw `payload` kwarg
    passed to `invoke_agent_runtime`, so the test can decode it and
    inspect the `repos` field without any real AWS call.
    """

    def __init__(self):
        self.captured_kwargs: dict | None = None

    def invoke_agent_runtime(self, **kwargs):
        self.captured_kwargs = kwargs
        response = MagicMock()
        # `_invoke_agent` does `response["response"].read().decode(...)`
        # then `json.loads(...)`, and re-parses if the result is a str.
        # `b"{}"` satisfies both: json.loads("{}") -> {} (a dict, not a
        # str), so the function returns immediately without a second
        # parse and without raising.
        response.read.return_value = b"{}"
        return {"response": response}


# Feature: gitlab-provider-support, Property 12: Agent invocation payload round trip
class TestProperty12AgentInvocationPayloadRoundTrip:
    """Property 12: for any list of repository descriptors — of arbitrary
    shape, since `_invoke_agent` never inspects or validates them — the
    JSON payload actually sent to `invoke_agent_runtime` carries a `repos`
    field that is structurally identical (via a `json.loads` round trip)
    to the original input list. No field is added, removed, renamed, or
    reordered within any descriptor, and no descriptor is added, dropped,
    or reordered within the list.

    Validates: Requirements 7.5
    """

    @given(repos=_P12_ARBITRARY_REPOS_STRATEGY)
    @settings(max_examples=20)
    def test_repos_are_forwarded_verbatim_into_the_invocation_payload(self, repos):
        with patch("handlers.correlation_worker.boto3.client") as mock_boto_client, \
             patch.dict(
                 os.environ,
                 {"CORRELATION_AGENT_RUNTIME_ARN": _P12_VALID_RUNTIME_ARN},
             ):
            fake_client = _P12FakeAgentCoreClient()
            mock_boto_client.return_value = fake_client

            _invoke_agent(
                user_id="user-prop12",
                start_date="2024-01-01",
                end_date="2024-01-07",
                git_username="octocat",
                repos=repos,
            )

            assert fake_client.captured_kwargs is not None
            raw_payload = fake_client.captured_kwargs["payload"]
            assert isinstance(raw_payload, bytes)

            decoded = json.loads(raw_payload.decode("utf-8"))

            # The round trip: `repos` in the payload actually sent is
            # structurally identical to the original input — same
            # descriptors, same fields per descriptor, same order. Since
            # both sides have already been through a JSON encode/decode
            # (the strategy only produces JSON-safe leaves), a plain `==`
            # here is exactly the "byte-for-byte via json.loads round
            # trip" comparison the property calls for.
            assert decoded["repos"] == repos

            # No field renamed within the top-level payload either: the
            # other fields the worker documents forwarding verbatim
            # (userId, startDate, endDate, gitUsername) are present and
            # unrelated to the repos round trip.
            assert decoded["userId"] == "user-prop12"
            assert decoded["startDate"] == "2024-01-01"
            assert decoded["endDate"] == "2024-01-07"
            assert decoded["gitUsername"] == "octocat"


# ----------------------------------------------------------------------
# Property 8: Agent token parameter derivation
# ----------------------------------------------------------------------

from agent.app.GitCorrelationAgent.tools.ssm_token import (
    REPO_ID_PATTERN,
    SSM_TOKEN_PATH_PREFIX as _P8_AGENT_SSM_TOKEN_PATH_PREFIX,
    fetch_repo_token,
)


class _P8ParameterNotFound(Exception):
    """Stand-in for the boto3 SSM client's generated exception class."""


class _P8FakeSsmExceptions:
    """Mimics the ``client.exceptions`` namespace boto3 SSM clients expose."""

    ParameterNotFound = _P8ParameterNotFound


class _P8FakeSsmClient:
    """Fake SSM client that always resolves successfully, recording every
    `get_parameter` call's `Name` and `WithDecryption` kwargs.

    What the parameter name was constructed as — and whether any call
    happened at all — is exactly what Property 8 checks; the returned
    value is irrelevant here, unlike the fake client used for Property 7.
    """

    exceptions = _P8FakeSsmExceptions

    def __init__(self):
        self.calls: list[dict] = []

    def get_parameter(self, Name: str, WithDecryption: bool = False):
        self.calls.append({"Name": Name, "WithDecryption": WithDecryption})
        return {"Parameter": {"Name": Name, "Value": "irrelevant"}}


_P8_VALID_REPO_ID_STRATEGY = st.text(
    alphabet="0123456789abcdef", min_size=8, max_size=8
)

# Invalid-shaped strings: wrong length (both shorter and longer all-hex
# strings), uppercase hex, non-hex letters at the right length, the empty
# string, whitespace-only and whitespace-padded values, and arbitrary
# (including Unicode) text. `assume(not REPO_ID_PATTERN.match(...))` below
# guards the rare case free text happens to be exactly 8 lowercase hex
# characters by chance.
_P8_INVALID_SHAPED_REPO_ID_STRATEGY = st.one_of(
    st.just(""),
    st.text(alphabet="0123456789abcdef", min_size=1, max_size=7),
    st.text(alphabet="0123456789abcdef", min_size=9, max_size=16),
    st.text(alphabet="0123456789ABCDEF", min_size=8, max_size=8),
    st.text(alphabet="ghijklmnopqrstuvwxyz", min_size=8, max_size=8),
    st.text(min_size=1, max_size=16),
    st.sampled_from([" ", "\t", "\n", "0a1b2c3d ", " 0a1b2c3d", "0a1b2c3d\n"]),
)

_P8_ANY_SHAPED_REPO_ID_STRATEGY = st.one_of(
    _P8_VALID_REPO_ID_STRATEGY,
    _P8_INVALID_SHAPED_REPO_ID_STRATEGY,
)


# Feature: gitlab-provider-support, Property 8: Agent token parameter derivation
class TestProperty8AgentTokenParameterDerivation:
    """Property 8: for any string matching `^[0-9a-f]{8}$`, the agent's
    token fetch requests exactly the parameter named
    `/kiro-cost-analyzer/git-tokens/{repoId}` with decryption enabled; and
    for any string failing that pattern, it issues no Parameter Store call
    at all and returns the empty string. `fetch_repo_token` never raises,
    for any string input.

    Validates: Requirements 3.4
    """

    @given(repo_id=_P8_VALID_REPO_ID_STRATEGY)
    @settings(max_examples=20)
    def test_valid_repo_id_requests_exactly_the_derived_parameter_name(
        self, repo_id
    ):
        fake_client = _P8FakeSsmClient()

        fetch_repo_token(repo_id, ssm_client=fake_client)

        # Exactly one SSM call, naming exactly the derived parameter, with
        # decryption enabled — the value the model reads back is a
        # secret, so WithDecryption must be True (unlike the backend's
        # existence-only check in Property 7).
        assert len(fake_client.calls) == 1
        call = fake_client.calls[0]
        assert call["Name"] == f"{_P8_AGENT_SSM_TOKEN_PATH_PREFIX}/{repo_id}"
        assert call["WithDecryption"] is True

    @given(repo_id=_P8_INVALID_SHAPED_REPO_ID_STRATEGY)
    @settings(max_examples=20)
    def test_invalid_shaped_repo_id_never_calls_ssm_and_returns_empty_string(
        self, repo_id
    ):
        assume(not REPO_ID_PATTERN.match(repo_id))

        fake_client = _P8FakeSsmClient()

        result = fetch_repo_token(repo_id, ssm_client=fake_client)

        # Validation happens before any SSM call: no call was ever made,
        # and the function falls back to the empty string.
        assert result == ""
        assert fake_client.calls == []

    @given(repo_id=_P8_ANY_SHAPED_REPO_ID_STRATEGY)
    @settings(max_examples=20)
    def test_totality_never_raises_for_any_string_input(self, repo_id):
        fake_client = _P8FakeSsmClient()

        try:
            fetch_repo_token(repo_id, ssm_client=fake_client)
        except Exception as exc:  # noqa: BLE001 — totality: nothing may raise
            raise AssertionError(
                f"fetch_repo_token raised for repo_id={repo_id!r}: {exc!r}"
            ) from exc


# ----------------------------------------------------------------------
# Property 3: GitLab request shape
# ----------------------------------------------------------------------

from unittest.mock import MagicMock, patch
from urllib.parse import quote

from agent.app.GitCorrelationAgent.tools.gitlab_tool import (
    API_PATH,
    MAX_COMMITS as _P3_MAX_COMMITS,
    MAX_MRS,
    REQUEST_TIMEOUT_SECONDS,
    build_gitlab_tool,
)

_P3_REPO_ID_STRATEGY = st.text(alphabet="0123456789abcdef", min_size=8, max_size=8)

_P3_HOST_LABEL_STRATEGY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8
)
_P3_HOST_STRATEGY = st.lists(_P3_HOST_LABEL_STRATEGY, min_size=1, max_size=3).map(
    ".".join
)
_P3_PORT_STRATEGY = st.one_of(st.none(), st.integers(min_value=1, max_value=65535))


def _p3_compose_base_url(scheme, host, port):
    netloc = host if port is None else f"{host}:{port}"
    return f"{scheme}://{netloc}"


# Both schemes are drawn — 10.3 requires plain `http` GitLab_Instances to
# work identically to `https` ones.
_P3_BASE_URL_STRATEGY = st.builds(
    _p3_compose_base_url,
    scheme=st.sampled_from(["http", "https"]),
    host=_P3_HOST_STRATEGY,
    port=_P3_PORT_STRATEGY,
)

_P3_PLAIN_SEGMENT_STRATEGY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=8
)

# A segment guaranteed to contain at least one character `quote(..., safe="")`
# must percent-encode (space, `@`, `#`, `%`, `&`, `+`, punctuation, and a
# couple of non-ASCII characters) — deterministically, rather than leaving
# it to chance whether any generated example ever exercises encoding.
_P3_ENCODING_WORTHY_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789 @#%&+:,()!$éñ"
_P3_SPECIAL_SEGMENT_STRATEGY = st.text(
    alphabet=_P3_ENCODING_WORTHY_CHARS, min_size=1, max_size=8
).filter(lambda s: any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in s))


@st.composite
def _p3_project_path_strategy(draw):
    """Compose a Namespace_Path with 1-4 subgroup segments, at least one of
    which always needs URL-encoding — exercising subgroup depth and the
    `quote(project_path, safe="")` encoding step together rather than
    leaving either to chance.
    """
    num_plain = draw(st.integers(min_value=0, max_value=3))
    plain_segments = draw(
        st.lists(
            _P3_PLAIN_SEGMENT_STRATEGY, min_size=num_plain, max_size=num_plain
        )
    )
    special_segment = draw(_P3_SPECIAL_SEGMENT_STRATEGY)
    position = draw(st.integers(min_value=0, max_value=len(plain_segments)))
    segments = plain_segments[:position] + [special_segment] + plain_segments[position:]
    return "/".join(segments)


_P3_AUTHOR_STRATEGY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_.", min_size=1, max_size=20
)

# A small pool of distinct ISO 8601 date/datetime strings — the shape
# `since` is documented to carry — rather than an open-ended date
# generator that adds no coverage this property needs.
_P3_SINCE_STRATEGY = st.sampled_from(
    [
        "2024-01-01",
        "2024-06-15",
        "2023-12-31T23:59:59Z",
        "2025-03-10T08:30:00+00:00",
    ]
)

_P3_TOKEN_VALUE = "prop3-private-token"  # noqa: S105 — test fixture value, not a real secret


class _P3FakeSsmClient:
    """Fake SSM client that always resolves to a fixed token value.

    Property 3 is about the shape of the *GitLab* HTTP request, not about
    token resolution (Property 8 owns that) — this fake only needs to let
    `_get_token` succeed so `get_gitlab_activity` reaches the `requests.get`
    calls under test.
    """

    def __init__(self, token: str):
        self._token = token

    def get_parameter(self, Name: str, WithDecryption: bool = False):
        return {"Parameter": {"Name": Name, "Value": self._token}}


def _p3_make_mock_response(json_value):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = json_value
    return response


# Feature: gitlab-provider-support, Property 3: GitLab request shape
class TestProperty3GitLabRequestShape:
    """Property 3: for any base URL, Namespace_Path (including subgroup
    segments that need URL-encoding), author, and `since` date, every
    `requests.get` call the GitLab_Tool issues:

    - targets a URL built from `base_url` + `API_PATH` ("/api/v4") + the
      URL-encoded (`quote(project_path, safe="")`) Namespace_Path + the
      correct endpoint suffix (`/repository/commits` for commits,
      `/merge_requests` for merge requests) — the fixed, GitLab-CE-only
      endpoint paths that are also the partial guard for criterion 10.2
      (no Premium/Ultimate/Duo endpoint is ever addressed);
    - authenticates via the `PRIVATE-TOKEN` header and never sends an
      `Authorization` header;
    - passes `timeout=REQUEST_TIMEOUT_SECONDS` (30);
    - never disables certificate verification (`verify` absent or `True`,
      never `False`);
    - carries the provider-specific query parameters: `since` and
      `per_page=100` for commits, and `author_username`, `created_after`,
      `state=all`, `per_page=50`, `order_by=updated_at`, `sort=desc` for
      merge requests.

    No real network call is made — `requests.get` is patched and every
    assertion is made against the captured call arguments — which is what
    makes a 100+ iteration budget affordable for this property.

    Validates: Requirements 4.4, 5.1, 5.2, 5.3, 5.8, 10.1, 10.3, 10.4
    """

    @given(
        repo_id=_P3_REPO_ID_STRATEGY,
        base_url=_P3_BASE_URL_STRATEGY,
        project_path=_p3_project_path_strategy(),
        author=_P3_AUTHOR_STRATEGY,
        since=_P3_SINCE_STRATEGY,
    )
    @settings(max_examples=20)
    @patch("agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get")
    def test_gitlab_requests_are_shaped_correctly_for_both_endpoints(
        self, mock_get, repo_id, base_url, project_path, author, since
    ):
        commits_response = _p3_make_mock_response([])
        mrs_response = _p3_make_mock_response([])
        mock_get.side_effect = [commits_response, mrs_response]

        fake_ssm = _P3FakeSsmClient(_P3_TOKEN_VALUE)
        tool_fn = build_gitlab_tool(ssm_client=fake_ssm)

        result = tool_fn(
            repo_id=repo_id,
            base_url=base_url,
            project_path=project_path,
            author=author,
            since=since,
        )

        # Sanity: with two 200 responses returning an empty list, the tool
        # must have reached both requests.get calls and produced a normal
        # (non-error) result — otherwise the assertions below would be
        # checking calls that were never made.
        assert "error" not in result
        assert mock_get.call_count == 2

        encoded_project_path = quote(project_path, safe="")
        expected_commits_url = (
            f"{base_url}{API_PATH}/projects/{encoded_project_path}/repository/commits"
        )
        expected_mrs_url = (
            f"{base_url}{API_PATH}/projects/{encoded_project_path}/merge_requests"
        )

        commits_call_args, commits_call_kwargs = mock_get.call_args_list[0]
        mrs_call_args, mrs_call_kwargs = mock_get.call_args_list[1]

        # 1. URL shape, per endpoint, including the URL-encoded Namespace
        # Path (4.4) and the GitLab-CE-only, hardcoded endpoint suffixes
        # (10.1, the partial guard for 10.2).
        assert commits_call_args[0] == expected_commits_url
        assert mrs_call_args[0] == expected_mrs_url

        # 2. PRIVATE-TOKEN header present, Authorization header absent, on
        # both calls (5.3).
        for kwargs in (commits_call_kwargs, mrs_call_kwargs):
            headers = kwargs["headers"]
            assert headers.get("PRIVATE-TOKEN") == _P3_TOKEN_VALUE
            assert "Authorization" not in headers

        # 3. Request timeout of 30 seconds on both calls (5.8).
        assert commits_call_kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS
        assert mrs_call_kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS
        assert REQUEST_TIMEOUT_SECONDS == 30

        # 4. Certificate verification never explicitly disabled, on either
        # call — `verify` is either absent (defaulting to True inside
        # `requests`) or explicitly `True`, never `False` (10.3's "http"
        # case is exercised by `base_url`'s scheme, not by `verify`).
        assert commits_call_kwargs.get("verify", True) is not False
        assert mrs_call_kwargs.get("verify", True) is not False

        # 5a. Commits query parameters (5.1, 10.4's base_url-derived
        # request completes with the right params regardless of scheme).
        commits_params = commits_call_kwargs["params"]
        assert commits_params["since"] == since
        assert commits_params["per_page"] == _P3_MAX_COMMITS
        assert _P3_MAX_COMMITS == 100

        # 5b. Merge request query parameters (5.2).
        mrs_params = mrs_call_kwargs["params"]
        assert mrs_params["author_username"] == author
        assert mrs_params["created_after"] == since
        assert mrs_params["state"] == "all"
        assert mrs_params["per_page"] == MAX_MRS
        assert mrs_params["order_by"] == "updated_at"
        assert mrs_params["sort"] == "desc"
        assert MAX_MRS == 50


# ----------------------------------------------------------------------
# Property 15: Normalized activity contract totality across providers
# ----------------------------------------------------------------------

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "agent", "app", "GitCorrelationAgent"
    ),
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agent.app.GitCorrelationAgent.tools.gitlab_tool import build_gitlab_tool

# ---- Malformed-payload generator --------------------------------------
#
# Property 15's whole claim is totality under garbage input, so this
# generator is deliberately hostile: most generated field VALUES are junk
# (None, wrong-typed scalars, deeply nested structures) rather than
# well-formed strings. A generator emitting only well-formed GitLab
# responses would make the property pass without testing the totality
# claim at all — the design's own generator note for Property 15.

_JUNK_LEAF = st.one_of(
    st.none(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.text(max_size=8),
)

# Deeply nested junk: lists/dicts of junk, built recursively via
# st.recursive and capped with max_leaves so Hypothesis does not spend its
# whole budget on structural depth rather than on breadth of shapes.
_JUNK_VALUE = st.recursive(
    _JUNK_LEAF,
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.text(max_size=5), children, max_size=3),
    ),
    max_leaves=6,
)

# A field value that is EITHER a plausible string OR outright junk (None,
# wrong type, deeply nested junk) — mixing valid-ish structures with
# garbage per the generator note, rather than sampling free text alone.
_FIELD_VALUE_STRATEGY = st.one_of(st.text(max_size=12), _JUNK_VALUE)

_COMMIT_FIELD_NAMES = [
    "id",
    "message",
    "authored_date",
    "committed_date",
    "created_at",
    "author_name",
    "author_email",
]

_COMMIT_EXTRA_KEYS = ["web_url", "parent_ids", "stats", "unexpected_field"]


@st.composite
def _p15_malformed_commit_item(draw):
    """A single commit item: a dict with a random subset of the fields
    `get_gitlab_activity` reads, each set to either a plausible string or
    junk. Fields not drawn into `present_fields` are simply absent —
    exercising the missing-key case — and a couple of unexpected extra
    keys are sometimes added, which the tool must ignore rather than
    choke on.
    """
    present_fields = draw(
        st.lists(
            st.sampled_from(_COMMIT_FIELD_NAMES),
            unique=True,
            max_size=len(_COMMIT_FIELD_NAMES),
        )
    )
    item = {field: draw(_FIELD_VALUE_STRATEGY) for field in present_fields}
    extra_keys = draw(
        st.lists(st.sampled_from(_COMMIT_EXTRA_KEYS), unique=True, max_size=2)
    )
    for key in extra_keys:
        item[key] = draw(_JUNK_VALUE)
    return item


# Commit list items are always dicts (possibly empty) — the malformation
# lives in which fields are present and what junk their values hold, not
# in the item's own top-level type. `commits_data` itself (the payload
# wrapping these items) is covered separately below and can be any shape.
_p15_commit_item_strategy = st.one_of(_p15_malformed_commit_item(), st.just({}))

_p15_commits_payload_strategy = st.one_of(
    st.lists(_p15_commit_item_strategy, max_size=5),
    st.none(),
    st.integers(),
    st.text(max_size=20),
    st.dictionaries(st.text(max_size=5), _JUNK_VALUE, max_size=3),
)

_MR_FIELD_NAMES = ["iid", "title", "state", "created_at"]
_MR_EXTRA_KEYS = ["web_url", "labels", "unexpected_field"]

# `author` is the one field the tool navigates two levels deep into
# (`mr.get("author", {}).get("username", "")`), so it gets its own
# deliberately hostile strategy: missing, explicit `None`, an empty dict,
# a dict whose `username` is itself junk, or unrelated junk entirely in
# place of a dict.
_P15_AUTHOR_STRATEGY = st.one_of(
    st.none(),
    st.just({}),
    st.builds(lambda u: {"username": u}, _FIELD_VALUE_STRATEGY),
    _JUNK_VALUE,
)


@st.composite
def _p15_malformed_mr_item(draw):
    present_fields = draw(
        st.lists(
            st.sampled_from(_MR_FIELD_NAMES),
            unique=True,
            max_size=len(_MR_FIELD_NAMES),
        )
    )
    item = {field: draw(_FIELD_VALUE_STRATEGY) for field in present_fields}
    if draw(st.booleans()):
        item["author"] = draw(_P15_AUTHOR_STRATEGY)
    extra_keys = draw(
        st.lists(st.sampled_from(_MR_EXTRA_KEYS), unique=True, max_size=2)
    )
    for key in extra_keys:
        item[key] = draw(_JUNK_VALUE)
    return item


_p15_mr_item_strategy = st.one_of(_p15_malformed_mr_item(), st.just({}))

_p15_mrs_payload_strategy = st.one_of(
    st.lists(_p15_mr_item_strategy, max_size=5),
    st.none(),
    st.integers(),
    st.text(max_size=20),
    st.dictionaries(st.text(max_size=5), _JUNK_VALUE, max_size=3),
)


def _p15_make_response(payload):
    """Build a fake `requests.Response` returning `payload` from `.json()`
    with `status_code=200`, so execution proceeds into the normalization
    path rather than an early error branch.
    """
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


# Feature: gitlab-provider-support, Property 15: Normalized activity contract totality across providers
class TestProperty15NormalizedActivityContractTotality:
    """Property 15: for any malformed GitLab API response on either the
    commits endpoint or the merge requests endpoint — missing keys,
    `None` values, wrong-typed values (integers where strings belong),
    deeply nested junk, empty dicts, and extra unexpected keys —
    `get_gitlab_activity` never raises, and its return value is always
    either an error object (an `error` code plus a `retryable` flag) or
    an activity object whose keys are exactly `commits` and
    `pull_requests`, both of which are always lists (never `None`, never
    missing) holding only dict items.

    Validates: Requirements 6.1
    """

    @given(
        commits_payload=_p15_commits_payload_strategy,
        mrs_payload=_p15_mrs_payload_strategy,
    )
    @settings(max_examples=20)
    def test_never_raises_and_always_returns_the_normalized_contract_shape(
        self, commits_payload, mrs_payload
    ):
        with patch(
            "agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token",
            return_value="fake-token",
        ), patch(
            "agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get"
        ) as mock_get:
            mock_get.side_effect = [
                _p15_make_response(commits_payload),
                _p15_make_response(mrs_payload),
            ]

            tool_fn = build_gitlab_tool()
            result = tool_fn(
                repo_id="deadbeef",
                base_url="https://gitlab.example.com",
                project_path="group/project",
                author="octocat",
                since="2024-01-01",
            )

        assert isinstance(result, dict)

        if "error" in result:
            assert isinstance(result["error"], str)
            assert isinstance(result["retryable"], bool)
            return

        # Totality of the Normalized_Activity_Contract: both keys are
        # always present and always lists — never None, never missing —
        # even when every field inside every item was garbage.
        assert "commits" in result
        assert "pull_requests" in result
        assert isinstance(result["commits"], list)
        assert isinstance(result["pull_requests"], list)

        for commit in result["commits"]:
            assert isinstance(commit, dict)

        for pr in result["pull_requests"]:
            assert isinstance(pr, dict)


# ----------------------------------------------------------------------
# Property 16: GitLab normalization field fidelity
# ----------------------------------------------------------------------

_P16_AUTHOR = "octocat"
_P16_SINCE = "2000-01-01T00:00:00Z"

# ISO 8601 strings composed from parts, all sharing the same fixed-width
# format ("YYYY-MM-DDTHH:MM:SSZ") and drawn from years well after
# _P16_SINCE's year — so every generated date sorts (lexicographically,
# which is how `_before_start_date` compares) after `_P16_SINCE` and is
# never excluded by the start-date filter. This keeps the property about
# field-mapping fidelity, not about which items survive filtering.
_P16_ISO_DATE_STRATEGY = st.builds(
    lambda year, month, day, hour, minute, second: (
        f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"
    ),
    year=st.integers(min_value=2020, max_value=2030),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.integers(min_value=0, max_value=59),
    second=st.integers(min_value=0, max_value=59),
)

_P16_TEXT_STRATEGY = st.text(min_size=0, max_size=30)
_P16_SHA_STRATEGY = st.text(alphabet="0123456789abcdef", min_size=7, max_size=40)


@st.composite
def _p16_commit_strategy(draw):
    """A well-formed commit item that survives the author filter (its
    `author_name` matches `_P16_AUTHOR` exactly) and exercises every
    branch of the `authored_date` > `committed_date` > `created_at`
    fallback chain:

    - "authored": only `authored_date` present -> it wins.
    - "authored_and_others": all three present -> `authored_date` still
      wins, proving the fallback chain checks in priority order rather
      than just picking whichever is present.
    - "committed": only `committed_date` present (no `authored_date`).
    - "created": only `created_at` present (no `authored_date`, no
      `committed_date`).

    Returns a `(item, expected_date)` tuple so the test can assert the
    exact expected mapping without re-deriving the fallback logic inline
    at the assertion site.
    """
    variant = draw(
        st.sampled_from(
            ["authored", "authored_and_others", "committed", "created"]
        )
    )
    authored_date = draw(_P16_ISO_DATE_STRATEGY)
    committed_date = draw(_P16_ISO_DATE_STRATEGY)
    created_at = draw(_P16_ISO_DATE_STRATEGY)

    item = {
        "id": draw(_P16_SHA_STRATEGY),
        "message": draw(_P16_TEXT_STRATEGY),
        "author_name": _P16_AUTHOR,
    }

    if variant == "authored":
        item["authored_date"] = authored_date
        expected_date = authored_date
    elif variant == "authored_and_others":
        item["authored_date"] = authored_date
        item["committed_date"] = committed_date
        item["created_at"] = created_at
        expected_date = authored_date
    elif variant == "committed":
        item["committed_date"] = committed_date
        expected_date = committed_date
    else:  # "created"
        item["created_at"] = created_at
        expected_date = created_at

    return item, expected_date


# Drawn verbatim from GitLab's own state vocabulary — never translated to
# a GitHub-style value ("open"/"closed"). "merged" and "locked" only exist
# in GitLab's vocabulary, which is exactly why they are included here:
# passing them through unchanged is the behavior this property pins down.
_P16_MR_STATE_STRATEGY = st.sampled_from(["opened", "closed", "merged", "locked"])


@st.composite
def _p16_mr_strategy(draw):
    """A well-formed merge request item that survives the author filter
    (its `author.username` matches `_P16_AUTHOR` exactly) and whose
    `created_at` sorts after `_P16_SINCE`.
    """
    return {
        "iid": draw(st.integers(min_value=0, max_value=10_000_000)),
        "title": draw(_P16_TEXT_STRATEGY),
        "state": draw(_P16_MR_STATE_STRATEGY),
        "created_at": draw(_P16_ISO_DATE_STRATEGY),
        "author": {"username": _P16_AUTHOR},
    }


# Feature: gitlab-provider-support, Property 16: GitLab normalization field fidelity
class TestProperty16GitLabNormalizationFieldFidelity:
    """Property 16: for well-formed GitLab commit and merge request items
    that pass the author filter, `get_gitlab_activity` maps every field
    exactly as the Normalized_Activity_Contract specifies:

    - Commits: `sha` <- `id`, `message` <- `message`, `date` <-
      `authored_date`, falling back to `committed_date`, then to
      `created_at`, in that priority order.
    - Merge requests (surfaced under `pull_requests`): `number` <- `iid`,
      `title` <- `title`, `state` <- the GitLab state value verbatim
      (never translated to any other vocabulary, e.g. "opened"/"merged"
      are passed through as-is rather than becoming "open"/"closed"),
      `created_at` <- `created_at`.

    This complements Property 15 (which drives malformed input through
    the same code path to check totality): here every generated item is
    well-formed and guaranteed to survive filtering, so the property can
    check the field values it produces rather than whether it survives.

    Validates: Requirements 6.2, 6.3
    """

    @given(
        commits=st.lists(_p16_commit_strategy(), min_size=1, max_size=5),
        mrs=st.lists(_p16_mr_strategy(), min_size=1, max_size=5),
    )
    @settings(max_examples=20)
    def test_field_mapping_is_exact_for_well_formed_items(self, commits, mrs):
        commit_items = [item for item, _expected_date in commits]

        with patch(
            "agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token",
            return_value="fake-token",
        ), patch(
            "agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get"
        ) as mock_get:
            mock_get.side_effect = [
                _p15_make_response(commit_items),
                _p15_make_response(mrs),
            ]

            tool_fn = build_gitlab_tool()
            result = tool_fn(
                repo_id="deadbeef",
                base_url="https://gitlab.example.com",
                project_path="group/project",
                author=_P16_AUTHOR,
                since=_P16_SINCE,
            )

        assert "error" not in result

        # No generated item should have been dropped: every commit's
        # author_name matches _P16_AUTHOR exactly and every commit's date
        # sorts after _P16_SINCE, and likewise every MR's author.username
        # matches and its created_at sorts after _P16_SINCE.
        assert len(result["commits"]) == len(commit_items)
        assert len(result["pull_requests"]) == len(mrs)

        # Order is preserved end to end (filtering never reorders), so
        # zipping the original inputs against the outputs pairs each
        # input with the output derived from it.
        for (input_item, expected_date), output_commit in zip(
            commits, result["commits"]
        ):
            assert output_commit["sha"] == input_item["id"]
            assert output_commit["message"] == input_item["message"]
            assert output_commit["date"] == expected_date

        for input_mr, output_pr in zip(mrs, result["pull_requests"]):
            assert output_pr["number"] == input_mr["iid"]
            assert output_pr["title"] == input_mr["title"]
            # Verbatim pass-through: the GitLab state value must appear
            # unchanged, not mapped to any other vocabulary.
            assert output_pr["state"] == input_mr["state"]
            assert output_pr["created_at"] == input_mr["created_at"]


# ----------------------------------------------------------------------
# Property 14: Provider-appropriate prompt terminology
# ----------------------------------------------------------------------

from agent.app.GitCorrelationAgent.prompts import build_user_prompt

_P14_REPO_ID_STRATEGY = st.text(alphabet="0123456789abcdef", min_size=8, max_size=8)

_P14_SIMPLE_TOKEN_STRATEGY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=10
)

# A github descriptor carries exactly the fields build_user_prompt's
# _render_repo_line reads for the "github" branch: provider, repoId,
# owner, repo, and its own gitUsername.
_P14_GITHUB_DESCRIPTOR_STRATEGY = st.builds(
    lambda repo_id, owner, repo, username: {
        "provider": "github",
        "repoId": repo_id,
        "owner": owner,
        "repo": repo,
        "gitUsername": username,
    },
    repo_id=_P14_REPO_ID_STRATEGY,
    owner=_P14_SIMPLE_TOKEN_STRATEGY,
    repo=_P14_SIMPLE_TOKEN_STRATEGY,
    username=_P14_SIMPLE_TOKEN_STRATEGY,
)

# A gitlab descriptor carries exactly the fields the "gitlab" branch
# reads: provider, repoId, baseUrl, projectPath, and its own gitUsername.
_P14_GITLAB_DESCRIPTOR_STRATEGY = st.builds(
    lambda repo_id, host_label, project_path, username: {
        "provider": "gitlab",
        "repoId": repo_id,
        "baseUrl": f"https://{host_label}.example.com",
        "projectPath": project_path,
        "gitUsername": username,
    },
    repo_id=_P14_REPO_ID_STRATEGY,
    host_label=_P14_SIMPLE_TOKEN_STRATEGY,
    project_path=_P14_SIMPLE_TOKEN_STRATEGY,
    username=_P14_SIMPLE_TOKEN_STRATEGY,
)

# The four shapes the property must cover: github-only (1-5 descriptors),
# gitlab-only (1-5 descriptors), mixed github+gitlab (1-3 of each), and
# the empty list. Combining them with st.one_of lets a single generator
# naturally produce all four across examples rather than needing four
# separate @given parametrizations.
_P14_GITHUB_ONLY_REPOS_STRATEGY = st.lists(
    _P14_GITHUB_DESCRIPTOR_STRATEGY, min_size=1, max_size=5
)

_P14_GITLAB_ONLY_REPOS_STRATEGY = st.lists(
    _P14_GITLAB_DESCRIPTOR_STRATEGY, min_size=1, max_size=5
)

_P14_MIXED_REPOS_STRATEGY = st.builds(
    lambda github_repos, gitlab_repos: github_repos + gitlab_repos,
    github_repos=st.lists(_P14_GITHUB_DESCRIPTOR_STRATEGY, min_size=1, max_size=3),
    gitlab_repos=st.lists(_P14_GITLAB_DESCRIPTOR_STRATEGY, min_size=1, max_size=3),
)

_P14_REPOS_STRATEGY = st.one_of(
    _P14_GITHUB_ONLY_REPOS_STRATEGY,
    _P14_GITLAB_ONLY_REPOS_STRATEGY,
    _P14_MIXED_REPOS_STRATEGY,
    st.just([]),
)


# Feature: gitlab-provider-support, Property 14: Provider-appropriate prompt terminology
class TestProperty14ProviderAppropriatePromptTerminology:
    """Property 14: for any list of repository descriptors — github-only,
    gitlab-only, mixed, or empty — `build_user_prompt` mentions the
    terminology block's github-specific line (the one calling out
    `get_github_activity`) if and only if at least one github descriptor
    is present, mentions the gitlab-specific line (calling out
    `get_gitlab_activity`) if and only if at least one gitlab descriptor
    is present, and lists every repository's `repoId` somewhere in the
    rendered repository listing.

    The assertions target `get_github_activity` / `get_gitlab_activity`
    rather than the looser substrings "pull request" / "merge request",
    because the latter also appear in the fixed output-contract reminder
    text that `build_user_prompt` always emits regardless of which
    providers are present (the `correlations[].type` reminder about
    "prompt_to_pr" and "prompt_to_mr"). `get_github_activity` and
    `get_gitlab_activity` only ever appear inside the conditional
    terminology block, so they unambiguously distinguish the two cases.

    Validates: Requirements 7.7
    """

    @given(repos=_P14_REPOS_STRATEGY)
    @settings(max_examples=20)
    def test_prompt_mentions_provider_terminology_iff_provider_present(
        self, repos
    ):
        has_github = any(repo.get("provider") == "github" for repo in repos)
        has_gitlab = any(repo.get("provider") == "gitlab" for repo in repos)

        prompt = build_user_prompt(
            user_id="user-1",
            start_date="2024-01-01",
            end_date="2024-01-31",
            git_username="fallback-user",
            repos=repos,
        )

        # The github-specific terminology line is present exactly when a
        # github descriptor is present in `repos` — never for a
        # gitlab-only or empty list.
        if has_github:
            assert "get_github_activity" in prompt
        else:
            assert "get_github_activity" not in prompt

        # The gitlab-specific terminology line is present exactly when a
        # gitlab descriptor is present in `repos` — never for a
        # github-only or empty list.
        if has_gitlab:
            assert "get_gitlab_activity" in prompt
        else:
            assert "get_gitlab_activity" not in prompt

        # Every repo is actually described in the rendered repository
        # listing, proving none is silently dropped.
        for repo in repos:
            assert repo["repoId"] in prompt


# ----------------------------------------------------------------------
# Property 18: GitLab error classification totality
# ----------------------------------------------------------------------

import requests as _p18_requests

# Scenario labels covering every distinct error-triggering branch in
# `get_gitlab_activity` (agent/app/GitCorrelationAgent/tools/gitlab_tool.py):
# no resolved token, each commits-call failure mode, and each merge-requests
# -call failure mode (including the one that is NOT an error dict — a
# network failure fetching merge requests after commits already succeeded
# yields the partial-success shape with a `warning` key).
_P18_ERROR_SCENARIOS = {
    "no_token": {"error": "GITLAB_AUTH_FAILED", "retryable": False},
    "commits_network_failure": {"error": "GITLAB_REQUEST_FAILED", "retryable": True},
    "commits_rate_limit": {"error": "GITLAB_RATE_LIMIT", "retryable": True},
    "commits_auth_401": {"error": "GITLAB_AUTH_FAILED", "retryable": False},
    "commits_auth_403": {"error": "GITLAB_AUTH_FAILED", "retryable": False},
    "commits_not_found_404": {"error": "GITLAB_REQUEST_FAILED", "retryable": True},
    "mrs_rate_limit": {"error": "GITLAB_RATE_LIMIT", "retryable": True},
    "mrs_auth_401": {"error": "GITLAB_AUTH_FAILED", "retryable": False},
    "mrs_auth_403": {"error": "GITLAB_AUTH_FAILED", "retryable": False},
}

# The one scenario that is deliberately NOT in the error-dict map above:
# a network failure on the merge-requests call, reached only after the
# commits call already succeeded, produces a partial-success dict instead
# of an error object.
_P18_MRS_NETWORK_FAILURE = "mrs_network_failure"

_P18_ALL_SCENARIOS = sorted(_P18_ERROR_SCENARIOS) + [_P18_MRS_NETWORK_FAILURE]

_P18_TOKEN_VALUE = "prop18-private-token"  # noqa: S105 — test fixture value, not a real secret


def _p18_make_response(status_code, json_value=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_value
    return response


def _p18_configure_mock_get(mock_get, scenario):
    """Set up `mock_get.side_effect` so that the commits call (and, where
    applicable, the merge requests call) triggers exactly the condition
    named by `scenario`.
    """
    if scenario == "commits_network_failure":
        mock_get.side_effect = [_p18_requests.RequestException("commits network failure")]
    elif scenario == "commits_rate_limit":
        mock_get.side_effect = [_p18_make_response(429)]
    elif scenario == "commits_auth_401":
        mock_get.side_effect = [_p18_make_response(401)]
    elif scenario == "commits_auth_403":
        mock_get.side_effect = [_p18_make_response(403)]
    elif scenario == "commits_not_found_404":
        mock_get.side_effect = [_p18_make_response(404)]
    elif scenario == _P18_MRS_NETWORK_FAILURE:
        # Commits call succeeds first (200, empty list) so the partial-
        # failure branch on the merge-requests call is actually reached.
        mock_get.side_effect = [
            _p18_make_response(200, []),
            _p18_requests.RequestException("mrs network failure"),
        ]
    elif scenario == "mrs_rate_limit":
        mock_get.side_effect = [_p18_make_response(200, []), _p18_make_response(429)]
    elif scenario == "mrs_auth_401":
        mock_get.side_effect = [_p18_make_response(200, []), _p18_make_response(401)]
    elif scenario == "mrs_auth_403":
        mock_get.side_effect = [_p18_make_response(200, []), _p18_make_response(403)]
    elif scenario == "no_token":
        # Token resolution fails before any HTTP call is made — mock_get
        # is configured but must never be invoked for this scenario.
        pass
    else:  # pragma: no cover - defensive, keeps scenario list exhaustive
        raise AssertionError(f"Unhandled scenario: {scenario!r}")


# Feature: gitlab-provider-support, Property 18: GitLab error classification totality
class TestProperty18GitLabErrorClassificationTotality:
    """Property 18: for every distinct error-triggering condition
    `get_gitlab_activity` can encounter — no resolved token; a network
    failure, HTTP 429, HTTP 401/403, or HTTP 404 on the commits call; and
    a network failure, HTTP 429, or HTTP 401/403 on the merge requests
    call — the tool never raises and returns exactly the documented error
    classification:

    - HTTP 401/403 anywhere, or no resolved token at all, returns
      `GITLAB_AUTH_FAILED` marked non-retryable (8.1);
    - HTTP 429 anywhere returns `GITLAB_RATE_LIMIT` marked retryable
      (8.2);
    - a network-level failure on the commits call, or an HTTP 404 on the
      commits call, returns `GITLAB_REQUEST_FAILED` marked retryable
      (8.3);
    - a network-level failure on the merge requests call, reached only
      after the commits call already succeeded, is NOT an error object —
      it is a partial-success dict carrying the commits already fetched,
      an empty `pull_requests` list, and a `warning` key.

    Totality: across every scenario, `get_gitlab_activity` always
    completes and returns a dict — it never raises. This is asserted
    implicitly: if any scenario below raised, the exception would
    propagate out of the `with patch(...)` block and fail this test
    before any assertion ran, since nothing here catches exceptions from
    the call under test.

    Validates: Requirements 8.1, 8.2, 8.3
    """

    @given(scenario=st.sampled_from(_P18_ALL_SCENARIOS))
    @settings(max_examples=20)
    def test_every_error_condition_classifies_exactly_as_documented(self, scenario):
        token_value = "" if scenario == "no_token" else _P18_TOKEN_VALUE

        with patch(
            "agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token",
            return_value=token_value,
        ), patch(
            "agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get"
        ) as mock_get:
            _p18_configure_mock_get(mock_get, scenario)

            tool_fn = build_gitlab_tool()

            # Totality: this call must complete and return a dict for
            # every scenario — no `except` here, so a raised exception
            # fails the test outright rather than being swallowed.
            result = tool_fn(
                repo_id="deadbeef",
                base_url="https://gitlab.example.com",
                project_path="group/project",
                author="octocat",
                since="2024-01-01",
            )

        assert isinstance(result, dict)

        if scenario == "no_token":
            # Token resolution fails before any HTTP call — the auth
            # failure is returned immediately.
            assert mock_get.call_count == 0
            assert result == _P18_ERROR_SCENARIOS[scenario]
            return

        if scenario == _P18_MRS_NETWORK_FAILURE:
            # Partial success, not an error dict: the commits already
            # fetched are kept, pull_requests is empty, and a warning
            # explains the merge-requests failure.
            assert "error" not in result
            assert result["commits"] == []
            assert result["pull_requests"] == []
            assert "warning" in result
            assert isinstance(result["warning"], str)
            return

        # Every remaining scenario is an error dict with exactly the
        # documented `error` code and `retryable` flag — nothing else.
        expected = _P18_ERROR_SCENARIOS[scenario]
        assert result == expected
        assert isinstance(result["error"], str)
        assert isinstance(result["retryable"], bool)


# ----------------------------------------------------------------------
# Property 13: Provider dispatch totality
# ----------------------------------------------------------------------
#
# `_normalize_descriptors` (agent/app/GitCorrelationAgent/main.py) is the
# mechanism that determines dispatch: the agent's system prompt tells the
# model to call the tool matching each descriptor's `provider` field, and
# a descriptor that survives normalization always carries a valid,
# supported provider plus that provider's required location fields.
# Testing the LLM's actual tool-calling decision is out of scope for a
# property test (no real model calls), so this property targets the
# deterministic normalization/defaulting logic that feeds dispatch.

from agent.app.GitCorrelationAgent.main import _normalize_descriptors

_P13_GITHUB_LOCATION = {"owner": "acme", "repo": "billing"}
_P13_GITLAB_LOCATION = {"baseUrl": "https://gitlab.example.com", "projectPath": "group/project"}


@st.composite
def _p13_github_descriptor(draw, complete: bool):
    """A descriptor with explicit `provider="github"`.

    When `complete` is True, both required location fields (`owner`,
    `repo`) are present and non-empty, so the descriptor survives
    normalization. When False, at least one is omitted, so it is dropped.
    """
    descriptor = {
        "repoId": draw(st.text(alphabet="0123456789abcdef", min_size=8, max_size=8)),
        "provider": "github",
    }
    if draw(st.booleans()):
        descriptor["gitUsername"] = draw(st.text(min_size=1, max_size=15))
    if complete:
        descriptor["owner"] = draw(st.text(min_size=1, max_size=15))
        descriptor["repo"] = draw(st.text(min_size=1, max_size=15))
    else:
        # Drop at least one of the two required fields.
        if draw(st.booleans()):
            descriptor["repo"] = draw(st.text(min_size=1, max_size=15))
        else:
            descriptor["owner"] = draw(st.text(min_size=1, max_size=15))
    return descriptor


@st.composite
def _p13_gitlab_descriptor(draw, complete: bool):
    """A descriptor with explicit `provider="gitlab"`.

    Mirrors `_p13_github_descriptor` for GitLab's required location
    fields (`baseUrl`, `projectPath`).
    """
    descriptor = {
        "repoId": draw(st.text(alphabet="0123456789abcdef", min_size=8, max_size=8)),
        "provider": "gitlab",
    }
    if draw(st.booleans()):
        descriptor["gitUsername"] = draw(st.text(min_size=1, max_size=15))
    if complete:
        descriptor["baseUrl"] = draw(st.text(min_size=1, max_size=30))
        descriptor["projectPath"] = draw(st.text(min_size=1, max_size=30))
    else:
        if draw(st.booleans()):
            descriptor["projectPath"] = draw(st.text(min_size=1, max_size=30))
        else:
            descriptor["baseUrl"] = draw(st.text(min_size=1, max_size=30))
    return descriptor


@st.composite
def _p13_no_provider_descriptor(draw, complete: bool):
    """A descriptor with NO `provider` key at all, exercising the
    github-default. When `complete`, it carries full `owner`/`repo` (and
    therefore survives defaulting to github); when not, it carries
    neither, so defaulting to github without location fields drops it.
    """
    descriptor = {
        "repoId": draw(st.text(alphabet="0123456789abcdef", min_size=8, max_size=8)),
    }
    if draw(st.booleans()):
        descriptor["gitUsername"] = draw(st.text(min_size=1, max_size=15))
    if complete:
        descriptor["owner"] = draw(st.text(min_size=1, max_size=15))
        descriptor["repo"] = draw(st.text(min_size=1, max_size=15))
    return descriptor


@st.composite
def _p13_unrecognized_provider_descriptor(draw):
    """A descriptor whose provider (after defaulting would not apply,
    since it is explicitly set to a non-empty, unsupported value) is
    never in `{"github", "gitlab"}` — always dropped regardless of how
    complete its location fields look.
    """
    provider = draw(
        st.one_of(
            st.sampled_from(["bitbucket", "svn", "perforce", "GITHUB", "GitLab"]),
            st.text(min_size=1, max_size=20).filter(
                lambda s: s not in ("github", "gitlab")
            ),
        )
    )
    descriptor = {
        "repoId": draw(st.text(alphabet="0123456789abcdef", min_size=8, max_size=8)),
        "provider": provider,
        # Give it every location field from both providers, so a bug that
        # ignores the provider check entirely would otherwise let it
        # through.
        "owner": "acme",
        "repo": "billing",
        "baseUrl": "https://gitlab.example.com",
        "projectPath": "group/project",
    }
    if draw(st.booleans()):
        descriptor["gitUsername"] = draw(st.text(min_size=1, max_size=15))
    return descriptor


_p13_non_dict_entry_strategy = st.one_of(
    st.none(),
    st.text(max_size=10),
    st.integers(),
)

_p13_entry_strategy = st.one_of(
    _p13_github_descriptor(complete=True),
    _p13_github_descriptor(complete=False),
    _p13_gitlab_descriptor(complete=True),
    _p13_gitlab_descriptor(complete=False),
    _p13_no_provider_descriptor(complete=True),
    _p13_no_provider_descriptor(complete=False),
    _p13_unrecognized_provider_descriptor(),
    _p13_non_dict_entry_strategy,
)


def _p13_had_recognized_provider_before_defaulting(entry) -> bool:
    return isinstance(entry, dict) and entry.get("provider") in ("github", "gitlab")


def _p13_had_required_location_fields(entry) -> bool:
    provider = entry.get("provider")
    if provider == "github":
        return bool(entry.get("owner")) and bool(entry.get("repo"))
    if provider == "gitlab":
        return bool(entry.get("baseUrl")) and bool(entry.get("projectPath"))
    return False


def _p13_identifying_fields(entry: dict) -> dict:
    """Extract the fields that must survive normalization unchanged for an
    input that already had a recognized provider, complete location
    fields, and a non-empty gitUsername before normalization ran.
    """
    fields = {}
    if "repoId" in entry:
        fields["repoId"] = entry["repoId"]
    provider = entry["provider"]
    if provider == "github":
        fields["owner"] = entry["owner"]
        fields["repo"] = entry["repo"]
    else:
        fields["baseUrl"] = entry["baseUrl"]
        fields["projectPath"] = entry["projectPath"]
    return fields


# Feature: gitlab-provider-support, Property 13: Provider dispatch totality
class TestProperty13ProviderDispatchTotality:
    """Property 13: for any list of incoming descriptors — including
    entries with an unknown provider, an absent provider, missing
    location fields, or non-dict junk mixed in — `_normalize_descriptors`
    terminates without raising; every retained descriptor carries a
    provider in {"github", "gitlab"}; every retained descriptor carries
    its own provider's required location fields, non-empty; and every
    retained descriptor carries a non-empty `gitUsername`. Since a
    descriptor's provider is exactly what the agent's prompt uses to pick
    the matching tool, and the required location fields are exactly
    github's or exactly gitlab's (never a mix), a descriptor that
    survives normalization can only ever be routed to the one tool
    matching its own provider — never the other one.

    Validates: Requirements 7.6
    """

    @given(
        repos=st.lists(_p13_entry_strategy, max_size=10),
        # Non-empty: a descriptor with no gitUsername of its own falls
        # back to this value (DD-5), so guaranteeing every retained
        # descriptor's gitUsername is non-empty (assertion 4 below)
        # requires the fallback itself to be non-empty. An empty fallback
        # is not itself a totality concern — it is already covered by the
        # existing example test `test_missing_git_username_falls_back_to_top_level`
        # and its sibling, which document the empty-fallback case directly.
        fallback_username=st.text(min_size=1, max_size=15),
    )
    @settings(max_examples=20)
    def test_normalize_descriptors_is_total_and_dispatch_correct(
        self, repos, fallback_username
    ):
        # 1. Totality: never raises, for any generated input.
        result = _normalize_descriptors(repos, fallback_username)

        assert isinstance(result, list)

        # 5. Dispatch only drops, never invents new descriptors.
        assert len(result) <= len(repos)

        for entry in result:
            # 2. Every retained entry has a recognized provider.
            assert entry["provider"] in ("github", "gitlab")

            # 3. Every retained entry has its provider's required
            #    location fields present and non-empty — never a mix of
            #    the two providers' fields, and never the other
            #    provider's tool being reachable for this descriptor.
            if entry["provider"] == "github":
                assert entry.get("owner")
                assert entry.get("repo")
            else:
                assert entry.get("baseUrl")
                assert entry.get("projectPath")

            # 4. Every retained entry has a non-empty gitUsername.
            assert entry.get("gitUsername")

        # 6. Every dict-shaped input entry that already had a recognized
        #    provider, complete required location fields, and a
        #    non-empty gitUsername BEFORE defaulting survives into the
        #    output unchanged in its identifying fields.
        already_valid_inputs = [
            entry
            for entry in repos
            if isinstance(entry, dict)
            and _p13_had_recognized_provider_before_defaulting(entry)
            and _p13_had_required_location_fields(entry)
            and entry.get("gitUsername")
        ]

        result_by_repo_id = {
            entry.get("repoId"): entry for entry in result if entry.get("repoId") is not None
        }

        for input_entry in already_valid_inputs:
            repo_id = input_entry.get("repoId")
            assert repo_id in result_by_repo_id, (
                "An already-valid input descriptor was dropped by "
                "normalization: %r" % (input_entry,)
            )
            output_entry = result_by_repo_id[repo_id]
            expected = _p13_identifying_fields(input_entry)
            for key, value in expected.items():
                assert output_entry[key] == value
            # gitUsername was already non-empty, so it must not have been
            # overridden by the fallback.
            assert output_entry["gitUsername"] == input_entry["gitUsername"]


# ----------------------------------------------------------------------
# Property 17: GitLab activity filtering and bounds
# ----------------------------------------------------------------------

import string as _p17_string

from agent.app.GitCorrelationAgent.tools.gitlab_tool import (
    MAX_COMMITS as _P17_MAX_COMMITS,
    MAX_MRS as _P17_MAX_MRS,
)

_P17_AUTHOR = "octocat"
_P17_SINCE = "2024-06-15T00:00:00Z"

# Three fixed, fixed-width ISO 8601 timestamps that sort lexicographically
# (and therefore chronologically, since `_before_start_date` compares
# strings directly) strictly before, exactly on, and strictly after
# `_P17_SINCE`. Sampling the category from these three rather than an
# open-ended date generator is what reliably produces the "before / on /
# after" mix the generator note asks for, rather than leaving it to
# chance whether all three ever occur together.
_P17_DATE_BEFORE = "2024-06-14T23:59:59Z"
_P17_DATE_ON = _P17_SINCE
_P17_DATE_AFTER = "2024-06-16T00:00:00Z"
_P17_DATE_BY_CATEGORY = {
    "before": _P17_DATE_BEFORE,
    "on": _P17_DATE_ON,
    "after": _P17_DATE_AFTER,
}

# Case-variation functions applied to the target author so that matching
# items sometimes carry a differently-cased author string, exercising the
# case-insensitive comparison in `_safe_lower` rather than always sending
# an exact-case match.
_P17_CASING_FUNCS = [str.lower, str.upper, str.title, str.capitalize, lambda s: s]

_P17_NON_MATCHING_AUTHOR_STRATEGY = st.text(
    alphabet=_p17_string.ascii_lowercase + _p17_string.digits, min_size=1, max_size=12
).filter(lambda s: s.lower() != _P17_AUTHOR.lower())


@st.composite
def _p17_commit_spec_list(draw):
    """Build a list of commit items tagged, BY CONSTRUCTION, with whether
    each one should survive the author filter and the start-date filter —
    so the test can check the tool's output against a ground truth
    computed from these tags rather than re-deriving the tool's own
    filtering logic.

    Three pools of items are combined, in order:

    1. `regular_specs` — a small Hypothesis-driven mix of
       (matches, date_category, field, casing) combinations, covering all
       3 (date category) x 2 (match/no-match) cases across the run rather
       than just one.
    2. A run of guaranteed matching-and-valid-date items, whose count is
       drawn from a range that sometimes exceeds MAX_COMMITS (100) — a
       count that never exceeds the cap would make the cap assertion
       vacuous.
    3. A run of guaranteed "noise" items (either non-matching author or a
       matching author with a before-`since` date), so the no-leak
       assertions always have something concrete to check.

    Returns `(items, is_match_flags, is_valid_date_flags)`, all the same
    length and in the same order as the generated `items` list.
    """
    regular_specs = draw(
        st.lists(
            st.tuples(
                st.booleans(),  # matches
                st.sampled_from(["before", "on", "after"]),  # date category
                st.sampled_from(["name", "email"]),  # which author field matches
                st.integers(min_value=0, max_value=len(_P17_CASING_FUNCS) - 1),
            ),
            min_size=3,
            max_size=12,
        )
    )

    # Skewed bimodally: mostly small, but sometimes comfortably past the
    # 100-commit cap, so the cap actually gets exercised across the run.
    extra_matching_valid_count = draw(
        st.one_of(
            st.integers(min_value=0, max_value=60),
            st.integers(min_value=95, max_value=130),
        )
    )

    extra_noise_count = draw(st.integers(min_value=0, max_value=10))
    extra_noise_kinds = draw(
        st.lists(
            st.sampled_from(["non_matching", "before_date"]),
            min_size=extra_noise_count,
            max_size=extra_noise_count,
        )
    )

    items: list[dict] = []
    is_match_flags: list[bool] = []
    is_valid_date_flags: list[bool] = []
    counter = 0

    def _next_id() -> str:
        nonlocal counter
        counter += 1
        return f"commit-sha-{counter:05d}"

    for matches, date_category, field, casing_idx in regular_specs:
        item_id = _next_id()
        date_value = _P17_DATE_BY_CATEGORY[date_category]
        if matches:
            cased_author = _P17_CASING_FUNCS[casing_idx](_P17_AUTHOR)
            item = {"id": item_id, "message": "m", "authored_date": date_value}
            if field == "name":
                item["author_name"] = cased_author
            else:
                item["author_email"] = cased_author
        else:
            other_author = draw(_P17_NON_MATCHING_AUTHOR_STRATEGY)
            item = {
                "id": item_id,
                "message": "m",
                "author_name": other_author,
                "authored_date": date_value,
            }
        items.append(item)
        is_match_flags.append(matches)
        is_valid_date_flags.append(date_category != "before")

    for _ in range(extra_matching_valid_count):
        item_id = _next_id()
        items.append(
            {
                "id": item_id,
                "message": "m",
                "author_name": _P17_AUTHOR,
                "authored_date": _P17_DATE_AFTER,
            }
        )
        is_match_flags.append(True)
        is_valid_date_flags.append(True)

    for kind in extra_noise_kinds:
        item_id = _next_id()
        if kind == "non_matching":
            other_author = draw(_P17_NON_MATCHING_AUTHOR_STRATEGY)
            items.append(
                {
                    "id": item_id,
                    "message": "m",
                    "author_name": other_author,
                    "authored_date": _P17_DATE_AFTER,
                }
            )
            is_match_flags.append(False)
            is_valid_date_flags.append(True)
        else:  # "before_date"
            items.append(
                {
                    "id": item_id,
                    "message": "m",
                    "author_name": _P17_AUTHOR,
                    "authored_date": _P17_DATE_BEFORE,
                }
            )
            is_match_flags.append(True)
            is_valid_date_flags.append(False)

    return items, is_match_flags, is_valid_date_flags


@st.composite
def _p17_mr_spec_list(draw):
    """Same construction as `_p17_commit_spec_list`, but for merge request
    items: the author field is always `author.username` (no name/email
    choice), the date field is `created_at`, and the cap that sometimes
    gets exceeded is MAX_MRS (50) rather than MAX_COMMITS.
    """
    regular_specs = draw(
        st.lists(
            st.tuples(
                st.booleans(),  # matches
                st.sampled_from(["before", "on", "after"]),  # date category
                st.integers(min_value=0, max_value=len(_P17_CASING_FUNCS) - 1),
            ),
            min_size=3,
            max_size=12,
        )
    )

    # Skewed bimodally around the 50-merge-request cap for the same
    # reason as the commit generator above.
    extra_matching_valid_count = draw(
        st.one_of(
            st.integers(min_value=0, max_value=30),
            st.integers(min_value=45, max_value=70),
        )
    )

    extra_noise_count = draw(st.integers(min_value=0, max_value=10))
    extra_noise_kinds = draw(
        st.lists(
            st.sampled_from(["non_matching", "before_date"]),
            min_size=extra_noise_count,
            max_size=extra_noise_count,
        )
    )

    items: list[dict] = []
    is_match_flags: list[bool] = []
    is_valid_date_flags: list[bool] = []
    counter = 0

    def _next_iid() -> int:
        nonlocal counter
        counter += 1
        return counter

    for matches, date_category, casing_idx in regular_specs:
        iid = _next_iid()
        date_value = _P17_DATE_BY_CATEGORY[date_category]
        if matches:
            cased_author = _P17_CASING_FUNCS[casing_idx](_P17_AUTHOR)
            author = {"username": cased_author}
        else:
            other_author = draw(_P17_NON_MATCHING_AUTHOR_STRATEGY)
            author = {"username": other_author}
        items.append(
            {
                "iid": iid,
                "title": "t",
                "state": "opened",
                "created_at": date_value,
                "author": author,
            }
        )
        is_match_flags.append(matches)
        is_valid_date_flags.append(date_category != "before")

    for _ in range(extra_matching_valid_count):
        iid = _next_iid()
        items.append(
            {
                "iid": iid,
                "title": "t",
                "state": "opened",
                "created_at": _P17_DATE_AFTER,
                "author": {"username": _P17_AUTHOR},
            }
        )
        is_match_flags.append(True)
        is_valid_date_flags.append(True)

    for kind in extra_noise_kinds:
        iid = _next_iid()
        if kind == "non_matching":
            other_author = draw(_P17_NON_MATCHING_AUTHOR_STRATEGY)
            items.append(
                {
                    "iid": iid,
                    "title": "t",
                    "state": "opened",
                    "created_at": _P17_DATE_AFTER,
                    "author": {"username": other_author},
                }
            )
            is_match_flags.append(False)
            is_valid_date_flags.append(True)
        else:  # "before_date"
            items.append(
                {
                    "iid": iid,
                    "title": "t",
                    "state": "opened",
                    "created_at": _P17_DATE_BEFORE,
                    "author": {"username": _P17_AUTHOR},
                }
            )
            is_match_flags.append(True)
            is_valid_date_flags.append(False)

    return items, is_match_flags, is_valid_date_flags


# Feature: gitlab-provider-support, Property 17: GitLab activity filtering and bounds
class TestProperty17GitLabActivityFilteringAndBounds:
    """Property 17: for any analysis start date, any mapped username, and
    any generated collections of commits and merge requests mixing
    matching and non-matching authors with dates spread before, on, and
    after the start date, `get_gitlab_activity`:

    - returns at most 100 commits and at most 50 merge requests;
    - returns no commit whose date sorts before `since`, and no merge
      request whose `created_at` sorts before `since`;
    - returns no commit and no merge request whose input item did not
      match the mapped author under case-insensitive comparison;
    - returns exactly the commits (respectively merge requests) that were
      both author-matching and date-valid, in their original order,
      truncated to the cap — i.e. every surviving item is accounted for by
      construction, not just "no unexpected item leaked through".

    Validates: Requirements 5.4, 5.5, 5.6, 5.7
    """

    @given(
        commit_spec=_p17_commit_spec_list(),
        mr_spec=_p17_mr_spec_list(),
    )
    @settings(max_examples=20)
    def test_filtering_and_bounds_hold_for_commits_and_merge_requests(
        self, commit_spec, mr_spec
    ):
        commit_items, commit_is_match, commit_is_valid_date = commit_spec
        mr_items, mr_is_match, mr_is_valid_date = mr_spec

        with patch(
            "agent.app.GitCorrelationAgent.tools.gitlab_tool.fetch_repo_token",
            return_value="fake-token",
        ), patch(
            "agent.app.GitCorrelationAgent.tools.gitlab_tool.requests.get"
        ) as mock_get:
            mock_get.side_effect = [
                _p15_make_response(commit_items),
                _p15_make_response(mr_items),
            ]

            tool_fn = build_gitlab_tool()
            result = tool_fn(
                repo_id="deadbeef",
                base_url="https://gitlab.example.com",
                project_path="group/project",
                author=_P17_AUTHOR,
                since=_P17_SINCE,
            )

        assert "error" not in result

        # ---- Commits ----------------------------------------------------

        # Ground truth computed from the construction tags, not from the
        # tool's own filtering logic: every item that both matched the
        # author and had a valid (on-or-after) date, in original order,
        # truncated to MAX_COMMITS.
        expected_commit_ids_all = [
            item["id"]
            for item, matches, valid_date in zip(
                commit_items, commit_is_match, commit_is_valid_date
            )
            if matches and valid_date
        ]
        expected_commit_ids = expected_commit_ids_all[:_P17_MAX_COMMITS]

        output_commit_ids = [c["sha"] for c in result["commits"]]

        # Exact accounting: the output is exactly the expected subset, in
        # order, capped — every surviving commit is accounted for.
        assert output_commit_ids == expected_commit_ids

        # The cap itself.
        assert len(result["commits"]) <= 100
        assert _P17_MAX_COMMITS == 100

        # No leaked items: neither a non-matching-author commit nor a
        # before-`since` commit ever appears in the output.
        leaked_commit_ids = {
            item["id"]
            for item, matches, valid_date in zip(
                commit_items, commit_is_match, commit_is_valid_date
            )
            if not (matches and valid_date)
        }
        assert leaked_commit_ids.isdisjoint(set(output_commit_ids))

        # Every output commit's date sorts on-or-after `since`.
        for commit in result["commits"]:
            assert not (commit["date"] < _P17_SINCE)

        # ---- Merge requests ----------------------------------------------

        expected_mr_ids_all = [
            item["iid"]
            for item, matches, valid_date in zip(
                mr_items, mr_is_match, mr_is_valid_date
            )
            if matches and valid_date
        ]
        expected_mr_ids = expected_mr_ids_all[:_P17_MAX_MRS]

        output_mr_numbers = [pr["number"] for pr in result["pull_requests"]]

        assert output_mr_numbers == expected_mr_ids

        assert len(result["pull_requests"]) <= 50
        assert _P17_MAX_MRS == 50

        leaked_mr_ids = {
            item["iid"]
            for item, matches, valid_date in zip(
                mr_items, mr_is_match, mr_is_valid_date
            )
            if not (matches and valid_date)
        }
        assert leaked_mr_ids.isdisjoint(set(output_mr_numbers))

        for pr in result["pull_requests"]:
            assert not (pr["created_at"] < _P17_SINCE)
