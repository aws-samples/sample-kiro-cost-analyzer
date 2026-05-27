"""Tests for identity-store-role.yaml CloudFormation helper template.

Regression guard for the IDC helper template that provisions the
``kiro-cost-analyzer-identity-store-read`` IAM role in the IDC account.

Ensures:
- The role name is pinned (cross-deployment discovery).
- The inline policy grants ONLY ``identitystore:DescribeUser`` and
  ``identitystore:ListUsers`` — no write or group actions may be added
  by accident.
- The trust policy restricts ``sts:AssumeRole`` to the KCA account via
  the ``aws:PrincipalAccount`` condition key, pinned to the
  ``KiroAccountId`` parameter.
- The stack exports ``IdentityStoreRoleArn`` for downstream consumers.

Feature: cross-account-identity-center (design task 7.2).
Requirements: 6.4, 6.5, 6.6, 6.7, 6.8, 9.3, 9.4.
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
# and by tools like ``cfn-lint``.


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


# Register constructors for every CFN intrinsic the helper template uses
# (and a few more for future-proofing).
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


TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "identity-store-role.yaml"
)


@pytest.fixture(scope="module")
def template() -> dict:
    """Load ``identity-store-role.yaml`` once per test module."""
    assert TEMPLATE_PATH.is_file(), (
        f"identity-store-role.yaml not found at {TEMPLATE_PATH}"
    )
    with TEMPLATE_PATH.open("r", encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_CfnLoader)  # noqa: S506 — _CfnLoader extends SafeLoader


@pytest.fixture(scope="module")
def role_resource(template: dict) -> dict:
    """Return the ``CrossAccountIdentityStoreRole`` resource properties."""
    resources = template["Resources"]
    assert "CrossAccountIdentityStoreRole" in resources, (
        "Template must define the CrossAccountIdentityStoreRole resource"
    )
    role = resources["CrossAccountIdentityStoreRole"]
    assert role["Type"] == "AWS::IAM::Role", (
        "CrossAccountIdentityStoreRole must be of type AWS::IAM::Role"
    )
    return role["Properties"]


# ---------------------------------------------------------------------------
# Role name (Requirement 6.8)
# ---------------------------------------------------------------------------


def test_role_name_is_pinned(role_resource: dict) -> None:
    """Role name is exactly ``kiro-cost-analyzer-identity-store-read``."""
    assert role_resource["RoleName"] == "kiro-cost-analyzer-identity-store-read"


# ---------------------------------------------------------------------------
# Inline policy — least-privilege read-only (Requirements 6.5, 6.6, 9.4)
# ---------------------------------------------------------------------------


def _managed_policy_statements(template: dict) -> list[dict]:
    """Get all statements from the IdentityStoreReadPolicy managed policy."""
    resources = template["Resources"]
    assert "IdentityStoreReadPolicy" in resources, (
        "Template must define the IdentityStoreReadPolicy resource"
    )
    policy = resources["IdentityStoreReadPolicy"]
    assert policy["Type"] == "AWS::IAM::ManagedPolicy"
    doc = policy["Properties"]["PolicyDocument"]
    stmt = doc["Statement"]
    if isinstance(stmt, dict):
        return [stmt]
    return stmt


def test_inline_policy_actions_are_exactly_two_read_only_actions(
    template: dict,
    role_resource: dict,
) -> None:
    """Managed policy grants exactly DescribeUser + ListUsers."""
    statements = _managed_policy_statements(template)

    # Collect every action granted by any Allow statement.
    granted_actions: set[str] = set()
    for stmt in statements:
        if stmt.get("Effect") != "Allow":
            continue
        action = stmt.get("Action")
        if isinstance(action, str):
            granted_actions.add(action)
        else:
            granted_actions.update(action)

    expected_actions = {
        "identitystore:DescribeUser",
        "identitystore:ListUsers",
    }
    assert granted_actions == expected_actions, (
        f"Managed policy must grant exactly {expected_actions}; got {granted_actions}"
    )


def test_inline_policy_forbids_write_and_group_actions(
    template: dict,
    role_resource: dict,
) -> None:
    """No write actions and no group-management actions may be granted."""
    statements = _managed_policy_statements(template)

    granted_actions: set[str] = set()
    for stmt in statements:
        if stmt.get("Effect") != "Allow":
            continue
        action = stmt.get("Action")
        if isinstance(action, str):
            granted_actions.add(action)
        else:
            granted_actions.update(action)

    forbidden_exact = {
        "identitystore:CreateUser",
        "identitystore:UpdateUser",
        "identitystore:DeleteUser",
    }
    forbidden_present = forbidden_exact & granted_actions
    assert not forbidden_present, (
        f"Write actions must not be granted; found {forbidden_present}"
    )

    group_actions = {a for a in granted_actions if "Group" in a}
    assert not group_actions, (
        f"Group-management actions must not be granted; found {group_actions}"
    )

    wildcard_actions = {a for a in granted_actions if a.endswith(":*") or a == "*"}
    assert not wildcard_actions, (
        f"Wildcard actions must not be granted; found {wildcard_actions}"
    )


# ---------------------------------------------------------------------------
# Trust policy — aws:PrincipalAccount pinned to KiroAccountId
# (Requirements 6.4, 9.3)
# ---------------------------------------------------------------------------


def test_trust_policy_is_pinned_to_kiro_account_id(role_resource: dict) -> None:
    """Trust policy restricts AssumeRole to the KCA account via aws:PrincipalAccount."""
    trust_doc = role_resource["AssumeRolePolicyDocument"]
    statements = trust_doc["Statement"]
    if isinstance(statements, dict):
        statements = [statements]

    assume_role_stmts = [
        s
        for s in statements
        if s.get("Effect") == "Allow"
        and (
            s.get("Action") == "sts:AssumeRole"
            or (
                isinstance(s.get("Action"), list)
                and "sts:AssumeRole" in s["Action"]
            )
        )
    ]
    assert assume_role_stmts, (
        "Trust policy must contain an Allow sts:AssumeRole statement"
    )

    # The template uses a single AssumeRole statement; assert it carries
    # the StringEquals/aws:PrincipalAccount condition pinned to KiroAccountId.
    stmt = assume_role_stmts[0]
    condition = stmt.get("Condition")
    assert condition is not None, (
        "Trust policy statement must define a Condition block"
    )

    string_equals = condition.get("StringEquals")
    assert string_equals is not None, (
        "Trust policy Condition must use StringEquals"
    )

    principal_account = string_equals.get("aws:PrincipalAccount")
    assert principal_account is not None, (
        "Trust policy must condition on aws:PrincipalAccount"
    )

    # Under the CfnLoader, ``!Ref KiroAccountId`` decodes to {"Ref": "KiroAccountId"}.
    assert principal_account == {"Ref": "KiroAccountId"}, (
        "aws:PrincipalAccount must be pinned to the KiroAccountId parameter; "
        f"got {principal_account!r}"
    )


# ---------------------------------------------------------------------------
# Outputs — IdentityStoreRoleArn export (Requirement 6.7)
# ---------------------------------------------------------------------------


def test_outputs_identity_store_role_arn_is_exported(template: dict) -> None:
    """``Outputs.IdentityStoreRoleArn`` is defined and exported by stack name."""
    outputs = template.get("Outputs") or {}
    assert "IdentityStoreRoleArn" in outputs, (
        "Template must define the IdentityStoreRoleArn output"
    )

    output = outputs["IdentityStoreRoleArn"]

    # Value points at the role's ARN via GetAtt. CloudFormation accepts two
    # short-form notations: ``!GetAtt Resource.Attr`` (dotted scalar) and
    # ``!GetAtt [Resource, Attr]`` (sequence). Both decode to ``Fn::GetAtt``
    # but with different value shapes, so accept either.
    value = output.get("Value")
    accepted_values = (
        {"Fn::GetAtt": ["CrossAccountIdentityStoreRole", "Arn"]},
        {"Fn::GetAtt": "CrossAccountIdentityStoreRole.Arn"},
    )
    assert value in accepted_values, (
        "IdentityStoreRoleArn output must be !GetAtt "
        f"CrossAccountIdentityStoreRole.Arn; got {value!r}"
    )

    # Export name is the stack-scoped canonical form.
    export = output.get("Export")
    assert export is not None, "IdentityStoreRoleArn output must declare an Export"

    export_name = export.get("Name")
    assert export_name == {
        "Fn::Sub": "${AWS::StackName}-IdentityStoreRoleArn"
    }, (
        "IdentityStoreRoleArn export name must be "
        "${AWS::StackName}-IdentityStoreRoleArn; "
        f"got {export_name!r}"
    )
