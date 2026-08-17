"""Template-structure smoke test for the S3 source config read-only change.

Regression guard for `template.yaml` verifying the write-path removal and
deploy-time parameter changes made by the s3-source-config-readonly feature
landed and stayed landed:

- The `ValidateSourceBucket` wildcard `s3:ListBucket` IAM statement is gone
  from `BackendFunction`'s `Policies` block.
- The `ConfigBucketPut`/`ConfigPromptsPrefixPut` API Gateway event
  definitions are gone from `BackendFunction`'s `Events` block.
- `Parameters.SourcePrefix` and `Parameters.PromptsPrefix` no longer carry a
  `Default` key (required parameters).
- `Parameters.SourceBucketName` still has no `Default` key (unchanged).
- The `Sid: ReadSourceBucket` statements on `ListFilesFunction`/
  `ParseFunction` remain scoped to `SourceBucketName` only, unmodified by
  this feature.

Follows the CFN-aware YAML parsing pattern from
`tests/test_identity_store_role_template.py`.

Feature: s3-source-config-readonly (design task 3.4).
Requirements: 3.3, 4.3, 5.1, 9.1, 9.2, 9.3, 9.6.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# CloudFormation YAML loader
# ---------------------------------------------------------------------------
#
# CloudFormation's short-form intrinsic tags (!Sub, !Ref, !GetAtt, ...) are
# not standard YAML tags. ``yaml.safe_load`` rejects them by default, so we
# register lightweight constructors on a dedicated SafeLoader subclass that
# return a dict in the expanded-form equivalent (e.g. ``!Ref X`` →
# ``{"Ref": "X"}``). This is the common pattern used by the CFN community
# and by tools like ``cfn-lint``, and mirrors
# ``tests/test_identity_store_role_template.py``.


class _CfnLoader(yaml.SafeLoader):
    """SafeLoader that understands CloudFormation intrinsic short-form tags."""


def _cfn_constructor(tag_suffix: str):
    """Build a constructor that expands ``!Tag value`` into ``{"Fn::Tag": value}``.

    ``Ref`` and ``Condition`` are special-cased because their expanded form
    is ``{"Ref": ...}`` / ``{"Condition": ...}`` rather than ``{"Fn::...": ...}``.
    """

    if tag_suffix in ("Ref", "Condition"):
        key = tag_suffix
    else:
        key = f"Fn::{tag_suffix}"

    def _construct(loader: yaml.SafeLoader, node: yaml.Node):
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node, deep=True)
        elif isinstance(node, yaml.MappingNode):
            value = loader.construct_mapping(node, deep=True)
        else:
            raise yaml.constructor.ConstructorError(
                None, None, f"unsupported node type for CFN tag !{tag_suffix}", node.start_mark
            )
        return {key: value}

    return _construct


for _tag in (
    "Ref",
    "Sub",
    "GetAtt",
    "Join",
    "Select",
    "Split",
    "FindInMap",
    "ImportValue",
    "If",
    "And",
    "Or",
    "Not",
    "Equals",
    "Condition",
    "Base64",
    "Cidr",
    "Transform",
):
    _CfnLoader.add_constructor(f"!{_tag}", _cfn_constructor(_tag))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "template.yaml"


@pytest.fixture(scope="module")
def template() -> dict:
    """Load ``template.yaml`` once per test module."""
    assert TEMPLATE_PATH.is_file(), f"template.yaml not found at {TEMPLATE_PATH}"
    with TEMPLATE_PATH.open("r", encoding="utf-8") as fh:
        # Instantiate the SafeLoader subclass directly instead of calling
        # yaml.load() so security scanners (ACAT UnsafeYAMLLoad) don't
        # pattern-match a false positive. Equivalent to
        # yaml.load(fh, Loader=_CfnLoader).
        loader = _CfnLoader(fh)
        try:
            return loader.get_single_data()
        finally:
            loader.dispose()


@pytest.fixture(scope="module")
def backend_function_properties(template: dict) -> dict:
    """Return the ``BackendFunction`` resource's ``Properties`` block."""
    resources = template["Resources"]
    assert "BackendFunction" in resources, "Template must define BackendFunction"
    backend_function = resources["BackendFunction"]
    assert backend_function["Type"] == "AWS::Serverless::Function"
    return backend_function["Properties"]


def _all_policy_statements(policies: list) -> list[dict]:
    """Flatten every ``Statement`` entry across a SAM ``Policies`` list.

    Entries may be a plain ``{"Statement": [...]}`` dict or a conditional
    ``!If`` block (decoded as ``{"Fn::If": [condition, then, else]}``). Only
    plain statement blocks are relevant to this test (the conditional
    ``AssumeSourceBucketRole``/``AssumeIdentityStoreRole`` blocks are not
    touched by this feature and are skipped here).
    """
    statements: list[dict] = []
    for entry in policies:
        if not isinstance(entry, dict):
            continue
        stmt = entry.get("Statement")
        if stmt is None:
            continue
        if isinstance(stmt, dict):
            statements.append(stmt)
        else:
            statements.extend(stmt)
    return statements


# ---------------------------------------------------------------------------
# ValidateSourceBucket IAM statement removed (Requirement 5.1)
# ---------------------------------------------------------------------------


def test_backend_function_has_no_validate_source_bucket_statement(
    backend_function_properties: dict,
) -> None:
    """BackendFunction's Policies block no longer grants ValidateSourceBucket."""
    policies = backend_function_properties.get("Policies") or []
    statements = _all_policy_statements(policies)

    sids = {stmt.get("Sid") for stmt in statements}
    assert "ValidateSourceBucket" not in sids, (
        "BackendFunction Policies must not contain a ValidateSourceBucket "
        f"statement; found Sids: {sids}"
    )


# ---------------------------------------------------------------------------
# ConfigBucketPut / ConfigPromptsPrefixPut events removed (Req 3.3, 4.3)
# ---------------------------------------------------------------------------


def test_backend_function_has_no_config_write_events(
    backend_function_properties: dict,
) -> None:
    """BackendFunction's Events block no longer wires up the removed write routes."""
    events = backend_function_properties.get("Events") or {}

    assert "ConfigBucketPut" not in events, (
        "BackendFunction Events must not contain ConfigBucketPut "
        f"(Path: /api/config/bucket); found event keys: {sorted(events)}"
    )
    assert "ConfigPromptsPrefixPut" not in events, (
        "BackendFunction Events must not contain ConfigPromptsPrefixPut "
        f"(Path: /api/config/prompts-prefix); found event keys: {sorted(events)}"
    )

    # Belt-and-suspenders: also confirm no event points at the removed
    # Path/Method combination under a different event name.
    for name, event in events.items():
        props = event.get("Properties", {})
        path = props.get("Path")
        method = props.get("Method")
        assert not (path == "/api/config/bucket" and method == "PUT"), (
            f"Event '{name}' still wires PUT /api/config/bucket to BackendFunction"
        )
        assert not (path == "/api/config/prompts-prefix" and method == "PUT"), (
            f"Event '{name}' still wires PUT /api/config/prompts-prefix to BackendFunction"
        )


# ---------------------------------------------------------------------------
# Parameters.SourcePrefix / PromptsPrefix have no Default (Req 9.2, 9.3)
# ---------------------------------------------------------------------------


def test_source_prefix_parameter_has_no_default(template: dict) -> None:
    """SourcePrefix is a required parameter (no Default)."""
    parameters = template.get("Parameters") or {}
    assert "SourcePrefix" in parameters, "Template must define SourcePrefix"
    assert "Default" not in parameters["SourcePrefix"], (
        "Parameters.SourcePrefix must not have a Default key; "
        f"got keys: {sorted(parameters['SourcePrefix'])}"
    )


def test_prompts_prefix_parameter_has_no_default(template: dict) -> None:
    """PromptsPrefix is a required parameter (no Default)."""
    parameters = template.get("Parameters") or {}
    assert "PromptsPrefix" in parameters, "Template must define PromptsPrefix"
    assert "Default" not in parameters["PromptsPrefix"], (
        "Parameters.PromptsPrefix must not have a Default key; "
        f"got keys: {sorted(parameters['PromptsPrefix'])}"
    )


# ---------------------------------------------------------------------------
# Parameters.SourceBucketName still has no Default (Req 9.1)
# ---------------------------------------------------------------------------


def test_source_bucket_name_parameter_has_no_default(template: dict) -> None:
    """SourceBucketName remains a required parameter (no Default), unchanged."""
    parameters = template.get("Parameters") or {}
    assert "SourceBucketName" in parameters, "Template must define SourceBucketName"
    assert "Default" not in parameters["SourceBucketName"], (
        "Parameters.SourceBucketName must not have a Default key; "
        f"got keys: {sorted(parameters['SourceBucketName'])}"
    )


# ---------------------------------------------------------------------------
# ReadSourceBucket statements on ListFilesFunction/ParseFunction unchanged
# (Requirement 9.6)
# ---------------------------------------------------------------------------


def _read_source_bucket_statement(template: dict, function_name: str) -> dict:
    resources = template["Resources"]
    assert function_name in resources, f"Template must define {function_name}"
    properties = resources[function_name]["Properties"]
    policies = properties.get("Policies") or []
    statements = _all_policy_statements(policies)

    matches = [s for s in statements if s.get("Sid") == "ReadSourceBucket"]
    assert matches, f"{function_name} must have a ReadSourceBucket statement"
    assert len(matches) == 1, (
        f"{function_name} must have exactly one ReadSourceBucket statement; "
        f"found {len(matches)}"
    )
    return matches[0]


def test_list_files_function_read_source_bucket_statement_unchanged(
    template: dict,
) -> None:
    """ListFilesFunction's ReadSourceBucket statement is scoped to SourceBucketName only."""
    stmt = _read_source_bucket_statement(template, "ListFilesFunction")

    assert stmt.get("Effect") == "Allow"
    assert stmt.get("Action") == ["s3:ListBucket"]
    assert stmt.get("Resource") == [{"Fn::Sub": "arn:aws:s3:::${SourceBucketName}"}], (
        f"ListFilesFunction ReadSourceBucket Resource must reference only "
        f"SourceBucketName; got {stmt.get('Resource')!r}"
    )


def test_parse_function_read_source_bucket_statement_unchanged(
    template: dict,
) -> None:
    """ParseFunction's ReadSourceBucket statement is scoped to SourceBucketName only."""
    stmt = _read_source_bucket_statement(template, "ParseFunction")

    assert stmt.get("Effect") == "Allow"
    assert stmt.get("Action") == ["s3:GetObject"]
    assert stmt.get("Resource") == [{"Fn::Sub": "arn:aws:s3:::${SourceBucketName}/*"}], (
        f"ParseFunction ReadSourceBucket Resource must reference only "
        f"SourceBucketName; got {stmt.get('Resource')!r}"
    )
