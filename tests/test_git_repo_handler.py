"""Tests for backend.handlers.git_repo_handler — repo CRUD + SSM token rollback.

Focus: the SSM/DynamoDB transaction ordering fix (Requirement 8.1).  When the
DynamoDB ``put_item`` fails after the SSM ``put_parameter`` succeeded, the
handler MUST roll back the SSM parameter so that no orphaned secret remains.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from backend.handlers.git_repo_handler import handle_create_repo, handle_update_repo


TABLE_NAME = "TestAnalyticsTable"


@pytest.fixture
def aws_env():
    """Mocked AWS environment with DynamoDB + SSM."""
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
        ssm = boto3.client("ssm", region_name="us-east-1")
        yield {"ddb": ddb, "ssm": ssm}


@pytest.fixture
def valid_body():
    return {
        "name": "my-repo",
        "url": "https://example.com/org/repo",
        "provider": "github",
        "accessToken": "ghp_test_token_value",
    }


@pytest.fixture
def claims():
    return {"userId": "admin-1", "groups": ["Admins"]}


# ------------------------------------------------------------------
# Happy path — basic sanity
# ------------------------------------------------------------------


class TestCreateRepoHappyPath:
    def test_persists_config_without_exposing_token(
        self, aws_env, valid_body, claims
    ):
        result = handle_create_repo(
            valid_body,
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=aws_env["ssm"],
        )

        assert result["_status_code"] == 201
        assert result["tokenConfigured"] is True
        assert "accessToken" not in result

        repo_id = result["repoId"]
        ssm_path = f"/kiro-cost-analyzer/git-tokens/{repo_id}"
        got = aws_env["ssm"].get_parameter(Name=ssm_path, WithDecryption=True)
        assert got["Parameter"]["Value"] == valid_body["accessToken"]

        table = aws_env["ddb"].Table(TABLE_NAME)
        item = table.get_item(
            Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"}
        ).get("Item")
        assert item is not None
        assert item["ssmTokenPath"] == ssm_path
        assert "accessToken" not in item
        assert valid_body["accessToken"] not in str(item)


# ------------------------------------------------------------------
# Regression: SSM rollback when DynamoDB write fails (B1)
# ------------------------------------------------------------------


class TestSsmRollbackOnDynamoFailure:
    def test_ssm_parameter_is_deleted_when_dynamo_put_fails(
        self, aws_env, valid_body, claims, monkeypatch
    ):
        captured: dict = {}
        from backend.handlers import git_repo_handler
        from git_shared import git_repository

        original_generate = git_repo_handler._generate_repo_id

        def spy_generate():
            rid = original_generate()
            captured["repo_id"] = rid
            return rid

        monkeypatch.setattr(git_repo_handler, "_generate_repo_id", spy_generate)

        def failing_put_repo_config(self, repo_id, config):
            raise ClientError(
                error_response={
                    "Error": {
                        "Code": "InternalServerError",
                        "Message": "simulated DynamoDB failure",
                    }
                },
                operation_name="PutItem",
            )

        monkeypatch.setattr(
            git_repository.GitRepository,
            "put_repo_config",
            failing_put_repo_config,
        )

        result = handle_create_repo(
            valid_body,
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=aws_env["ssm"],
        )

        assert result["_status_code"] == 500
        assert result["error"] == "InternalError"
        assert valid_body["accessToken"] not in str(result)

        repo_id = captured["repo_id"]
        ssm_path = f"/kiro-cost-analyzer/git-tokens/{repo_id}"
        with pytest.raises(aws_env["ssm"].exceptions.ParameterNotFound):
            aws_env["ssm"].get_parameter(Name=ssm_path)

        table = aws_env["ddb"].Table(TABLE_NAME)
        item = table.get_item(
            Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"}
        ).get("Item")
        assert item is None

    def test_returns_500_even_when_rollback_also_fails(
        self, aws_env, valid_body, claims, monkeypatch
    ):
        from backend.handlers import git_repo_handler
        from git_shared import git_repository

        def failing_put_repo_config(self, repo_id, config):
            raise RuntimeError("DynamoDB exploded")

        monkeypatch.setattr(
            git_repository.GitRepository,
            "put_repo_config",
            failing_put_repo_config,
        )

        fake_ssm = MagicMock()
        fake_ssm.put_parameter.return_value = {}
        fake_ssm.delete_parameter.side_effect = RuntimeError("SSM unreachable")

        result = handle_create_repo(
            valid_body,
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=fake_ssm,
        )

        assert result["_status_code"] == 500
        assert result["error"] == "InternalError"
        fake_ssm.delete_parameter.assert_called_once()


# ------------------------------------------------------------------
# Validation errors
# ------------------------------------------------------------------


class TestValidationErrors:
    def test_rejects_invalid_url(self, aws_env, claims):
        body = {
            "name": "r",
            "url": "not-a-url",
            "provider": "github",
            "accessToken": "t",
        }
        result = handle_create_repo(
            body,
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=aws_env["ssm"],
        )
        assert result["_status_code"] == 400
        assert result["error"] == "ValidationError"

    def test_rejects_unsupported_provider(self, aws_env, claims):
        body = {
            "name": "r",
            "url": "https://example.com/x",
            "provider": "subversion",
            "accessToken": "t",
        }
        result = handle_create_repo(
            body,
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=aws_env["ssm"],
        )
        assert result["_status_code"] == 400
        assert result["error"] == "ValidationError"


# ------------------------------------------------------------------
# PATCH /api/git/repos/{repoId} — partial update / token rotation
# Feature: git-repo-edit-token-rotation
# ------------------------------------------------------------------


def _create_seed_repo(aws_env, valid_body, claims) -> str:
    """Creates a repo via the real create handler and returns its repoId."""
    result = handle_create_repo(
        valid_body,
        claims,
        dynamodb_resource=aws_env["ddb"],
        ssm_client=aws_env["ssm"],
    )
    assert result["_status_code"] == 201
    return result["repoId"]


class TestUpdateRepoIdentityStability:
    """Feature: git-repo-edit-token-rotation, Property 1: Identity stability."""

    def test_identity_fields_unchanged_after_full_patch(
        self, aws_env, valid_body, claims
    ):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        table = aws_env["ddb"].Table(TABLE_NAME)
        before = table.get_item(Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"})["Item"]

        result = handle_update_repo(
            repo_id,
            {
                "name": "renamed-repo",
                "url": "https://example.com/org/renamed",
                "provider": "gitlab",
                "accessToken": "glpat_new_rotated_token",
            },
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=aws_env["ssm"],
        )

        assert "_status_code" not in result  # 200
        after = table.get_item(Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"})["Item"]
        assert result["repoId"] == repo_id
        assert after["createdAt"] == before["createdAt"]
        assert after["createdBy"] == before["createdBy"]
        assert after["ssmTokenPath"] == before["ssmTokenPath"]
        assert result["createdAt"] == before["createdAt"]


class TestUpdateRepoPartiality:
    """Feature: git-repo-edit-token-rotation, Property 2: Partiality."""

    def test_metadata_only_patch_keeps_token_untouched(
        self, aws_env, valid_body, claims
    ):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        ssm_path = f"/kiro-cost-analyzer/git-tokens/{repo_id}"

        result = handle_update_repo(
            repo_id,
            {"name": "typo-fixed"},
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=aws_env["ssm"],
        )

        assert result["name"] == "typo-fixed"
        # Absent fields retained
        assert result["url"] == valid_body["url"]
        assert result["provider"] == valid_body["provider"]
        # Token untouched
        got = aws_env["ssm"].get_parameter(Name=ssm_path, WithDecryption=True)
        assert got["Parameter"]["Value"] == valid_body["accessToken"]

    def test_token_only_patch_rotates_in_place_and_keeps_metadata(
        self, aws_env, valid_body, claims
    ):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        ssm_path = f"/kiro-cost-analyzer/git-tokens/{repo_id}"
        new_token = "ghp_rotated_token_value_2"

        result = handle_update_repo(
            repo_id,
            {"accessToken": new_token},
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=aws_env["ssm"],
        )

        # Same parameter path now holds the new token (rotation in place)
        got = aws_env["ssm"].get_parameter(Name=ssm_path, WithDecryption=True)
        assert got["Parameter"]["Value"] == new_token
        # Metadata retained
        assert result["name"] == valid_body["name"]
        assert result["url"] == valid_body["url"]
        assert result["tokenConfigured"] is True


class TestUpdateRepoSecretHygiene:
    """Feature: git-repo-edit-token-rotation, Property 3: Secret hygiene."""

    def test_token_never_in_response_or_persisted_item(
        self, aws_env, valid_body, claims
    ):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        new_token = "ghp_secret_rotation_value"

        result = handle_update_repo(
            repo_id,
            {"accessToken": new_token, "name": "renamed"},
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=aws_env["ssm"],
        )

        assert new_token not in str(result)
        assert "ssmTokenPath" not in result
        table = aws_env["ddb"].Table(TABLE_NAME)
        item = table.get_item(Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"})["Item"]
        assert new_token not in str(item)


class TestUpdateRepoValidationAndErrors:
    def test_unknown_repo_returns_404(self, aws_env, claims):
        result = handle_update_repo(
            "nonexistent",
            {"name": "x"},
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=aws_env["ssm"],
        )
        assert result["_status_code"] == 404
        assert result["error"] == "NotFound"

    def test_empty_body_returns_400(self, aws_env, valid_body, claims):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        result = handle_update_repo(
            repo_id, {}, claims,
            dynamodb_resource=aws_env["ddb"], ssm_client=aws_env["ssm"],
        )
        assert result["_status_code"] == 400
        assert result["error"] == "ValidationError"

    def test_irrelevant_fields_only_returns_400(self, aws_env, valid_body, claims):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        result = handle_update_repo(
            repo_id, {"status": "SYNC_OK", "repoId": "hijack"}, claims,
            dynamodb_resource=aws_env["ddb"], ssm_client=aws_env["ssm"],
        )
        assert result["_status_code"] == 400

    def test_invalid_url_returns_400(self, aws_env, valid_body, claims):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        result = handle_update_repo(
            repo_id, {"url": "not-a-url"}, claims,
            dynamodb_resource=aws_env["ddb"], ssm_client=aws_env["ssm"],
        )
        assert result["_status_code"] == 400

    def test_unsupported_provider_returns_400(self, aws_env, valid_body, claims):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        result = handle_update_repo(
            repo_id, {"provider": "subversion"}, claims,
            dynamodb_resource=aws_env["ddb"], ssm_client=aws_env["ssm"],
        )
        assert result["_status_code"] == 400

    def test_short_token_returns_400(self, aws_env, valid_body, claims):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        result = handle_update_repo(
            repo_id, {"accessToken": "short"}, claims,
            dynamodb_resource=aws_env["ddb"], ssm_client=aws_env["ssm"],
        )
        assert result["_status_code"] == 400

    def test_ssm_failure_aborts_without_metadata_change(
        self, aws_env, valid_body, claims
    ):
        repo_id = _create_seed_repo(aws_env, valid_body, claims)
        failing_ssm = MagicMock()
        failing_ssm.put_parameter.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "boom"}},
            "PutParameter",
        )

        result = handle_update_repo(
            repo_id,
            {"name": "should-not-persist", "accessToken": "ghp_new_token_value"},
            claims,
            dynamodb_resource=aws_env["ddb"],
            ssm_client=failing_ssm,
        )

        assert result["_status_code"] == 500
        assert "ghp_new_token_value" not in str(result)
        # Metadata untouched (SSM-before-DynamoDB ordering)
        table = aws_env["ddb"].Table(TABLE_NAME)
        item = table.get_item(Key={"PK": f"GITREPO#{repo_id}", "SK": "CONFIG"})["Item"]
        assert item["name"] == valid_body["name"]
