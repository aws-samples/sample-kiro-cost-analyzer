"""Tests for backend.handlers.git_mapping_handler — mapping CRUD (upsert + delete).

Focus areas (task 6.4, Requirements 2.9, 2.11):

- ``gitlab`` is an accepted provider, and a single user can hold both a
  ``github`` and a ``gitlab`` mapping simultaneously (coexistence).
- ``handle_create_mapping`` is an upsert: creating a second mapping for a
  user+provider pair that already has one returns ``replaced: true`` and
  ``previousGitUsername`` set to the old username; creating a mapping for a
  pair with no prior mapping returns ``replaced: false`` with no
  ``previousGitUsername``.
- ``handle_delete_mapping`` is idempotent: deleting an existing pair twice,
  and deleting a pair that never existed, both succeed with the same
  response shape (no 404 branch exists for delete).
"""

from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws

from backend.handlers.git_mapping_handler import (
    handle_create_mapping,
    handle_delete_mapping,
    handle_list_mappings,
)


TABLE_NAME = "TestAnalyticsTable"


@pytest.fixture
def aws_env():
    """Mocked DynamoDB environment with the standard PK/SK schema."""
    with mock_aws():
        os.environ["ANALYTICS_TABLE"] = TABLE_NAME
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
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
        yield ddb


@pytest.fixture
def claims():
    return {"userId": "admin-1", "groups": ["Admins"]}


def _seed_user(ddb, user_id: str = "user-1"):
    """Seed a minimal item so `_user_exists` passes for this userId."""
    table = ddb.Table(TABLE_NAME)
    table.put_item(Item={"PK": f"USER#{user_id}", "SK": "STATS#DAILY#2024-01-01"})


# ------------------------------------------------------------------
# gitlab acceptance + coexistence
# ------------------------------------------------------------------


class TestGitlabAcceptedAndCoexistence:
    def test_creating_a_gitlab_mapping_is_accepted(self, aws_env, claims):
        _seed_user(aws_env)

        result = handle_create_mapping(
            {"userId": "user-1", "provider": "gitlab", "gitUsername": "gl-user"},
            claims,
            dynamodb_resource=aws_env,
        )

        assert result["_status_code"] == 201
        assert result["provider"] == "gitlab"
        assert result["gitUsername"] == "gl-user"

    def test_one_user_can_hold_both_github_and_gitlab_mappings(self, aws_env, claims):
        _seed_user(aws_env)

        handle_create_mapping(
            {"userId": "user-1", "provider": "github", "gitUsername": "gh-user"},
            claims,
            dynamodb_resource=aws_env,
        )
        handle_create_mapping(
            {"userId": "user-1", "provider": "gitlab", "gitUsername": "gl-user"},
            claims,
            dynamodb_resource=aws_env,
        )

        listed = handle_list_mappings("user-1", dynamodb_resource=aws_env)
        by_provider = {m["provider"]: m["gitUsername"] for m in listed["mappings"]}

        assert by_provider == {"github": "gh-user", "gitlab": "gl-user"}
        assert len(listed["mappings"]) == 2


# ------------------------------------------------------------------
# Upsert: replaced / previousGitUsername
# ------------------------------------------------------------------


class TestUpsertReplacementReporting:
    def test_second_mapping_for_same_pair_reports_replaced_true_with_previous_username(
        self, aws_env, claims
    ):
        _seed_user(aws_env)

        handle_create_mapping(
            {"userId": "user-1", "provider": "gitlab", "gitUsername": "old-user"},
            claims,
            dynamodb_resource=aws_env,
        )
        result = handle_create_mapping(
            {"userId": "user-1", "provider": "gitlab", "gitUsername": "new-user"},
            claims,
            dynamodb_resource=aws_env,
        )

        assert result["_status_code"] == 201
        assert result["replaced"] is True
        assert result["previousGitUsername"] == "old-user"
        assert result["gitUsername"] == "new-user"

        # The new username persists on read.
        listed = handle_list_mappings("user-1", dynamodb_resource=aws_env)
        gitlab_mappings = [m for m in listed["mappings"] if m["provider"] == "gitlab"]
        assert len(gitlab_mappings) == 1
        assert gitlab_mappings[0]["gitUsername"] == "new-user"

    def test_first_mapping_for_a_pair_reports_replaced_false_with_no_previous_username(
        self, aws_env, claims
    ):
        _seed_user(aws_env)

        result = handle_create_mapping(
            {"userId": "user-1", "provider": "gitlab", "gitUsername": "first-user"},
            claims,
            dynamodb_resource=aws_env,
        )

        assert result["_status_code"] == 201
        assert result["replaced"] is False
        assert result["previousGitUsername"] is None


# ------------------------------------------------------------------
# Delete idempotence (Requirement 2.9)
# ------------------------------------------------------------------


class TestDeleteIdempotence:
    def test_deleting_an_existing_pair_twice_both_succeed_with_same_shape(
        self, aws_env, claims
    ):
        _seed_user(aws_env)
        handle_create_mapping(
            {"userId": "user-1", "provider": "gitlab", "gitUsername": "gl-user"},
            claims,
            dynamodb_resource=aws_env,
        )

        first = handle_delete_mapping("user-1", "gitlab", dynamodb_resource=aws_env)
        second = handle_delete_mapping("user-1", "gitlab", dynamodb_resource=aws_env)

        expected_shape = {"userId": "user-1", "provider": "gitlab", "deleted": True}
        assert first == expected_shape
        assert second == expected_shape

        # Confirm it is actually gone after the first call.
        listed = handle_list_mappings("user-1", dynamodb_resource=aws_env)
        assert listed["mappings"] == []

    def test_deleting_a_pair_that_never_existed_succeeds_like_a_real_deletion(
        self, aws_env, claims
    ):
        result = handle_delete_mapping(
            "user-never-had-one", "gitlab", dynamodb_resource=aws_env
        )

        assert result == {
            "userId": "user-never-had-one",
            "provider": "gitlab",
            "deleted": True,
        }
