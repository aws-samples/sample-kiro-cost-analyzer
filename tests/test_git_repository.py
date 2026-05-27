"""Tests for backend.repository.git_repository — Git DynamoDB operations."""

from __future__ import annotations

import os
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from git_shared.git_repository import GitRepository


TABLE_NAME = "TestAnalyticsTable"


@pytest.fixture
def dynamodb_resource():
    """Create a mocked DynamoDB table for testing."""
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-east-1")
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
        yield resource


@pytest.fixture
def repo(dynamodb_resource):
    """Return a GitRepository wired to the mocked table."""
    return GitRepository(TABLE_NAME, dynamodb_resource=dynamodb_resource)


@pytest.fixture
def table(dynamodb_resource):
    """Return the raw DynamoDB Table for direct assertions."""
    return dynamodb_resource.Table(TABLE_NAME)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

class TestConvertDecimals:
    def test_converts_decimal_int(self):
        assert GitRepository._convert_decimals(Decimal("42")) == 42

    def test_converts_decimal_float(self):
        assert GitRepository._convert_decimals(Decimal("3.14")) == 3.14

    def test_converts_nested_dict(self):
        data = {"a": Decimal("1"), "b": [Decimal("2.5")]}
        result = GitRepository._convert_decimals(data)
        assert result == {"a": 1, "b": [2.5]}

    def test_passthrough_non_decimal(self):
        assert GitRepository._convert_decimals("hello") == "hello"


class TestPaginationTokens:
    def test_encode_decode_roundtrip(self):
        key = {"PK": "USER#abc", "SK": "GITCOMMIT#2025-01-01#hash1"}
        token = GitRepository._encode_next_token(key)
        assert token is not None
        decoded = GitRepository._decode_next_token(token)
        assert decoded == key

    def test_encode_none(self):
        assert GitRepository._encode_next_token(None) is None

    def test_decode_none(self):
        assert GitRepository._decode_next_token(None) is None


# ------------------------------------------------------------------
# 1. Repo configs
# ------------------------------------------------------------------

class TestRepoConfigs:
    def test_put_and_get(self, repo):
        config = {
            "name": "my-repo",
            "url": "https://github.com/org/repo",
            "provider": "github",
            "ssmTokenPath": "/kiro-cost-analyzer/git-tokens/r1",
            "status": "ACTIVE",
            "createdAt": "2025-01-15T10:00:00Z",
            "createdBy": "admin-1",
        }
        repo.put_repo_config("r1", config)
        result = repo.get_repo_config("r1")

        assert result is not None
        assert result["PK"] == "GITREPO#r1"
        assert result["SK"] == "CONFIG"
        assert result["name"] == "my-repo"
        assert result["provider"] == "github"

    def test_get_nonexistent(self, repo):
        assert repo.get_repo_config("nonexistent") is None

    def test_list_repo_configs(self, repo):
        repo.put_repo_config("r1", {"name": "repo-1", "provider": "github", "status": "ACTIVE"})
        repo.put_repo_config("r2", {"name": "repo-2", "provider": "gitlab", "status": "ACTIVE"})

        configs = repo.list_repo_configs()
        assert len(configs) == 2
        names = {c["name"] for c in configs}
        assert names == {"repo-1", "repo-2"}

    def test_delete_repo_config(self, repo):
        repo.put_repo_config("r1", {"name": "repo-1", "provider": "github", "status": "ACTIVE"})
        repo.delete_repo_config("r1")
        assert repo.get_repo_config("r1") is None

    def test_update_sync_status(self, repo):
        repo.put_repo_config("r1", {"name": "repo-1", "provider": "github", "status": "ACTIVE"})
        repo.update_repo_sync_status("r1", "SYNC_OK", "2025-01-15T23:59:00Z")

        result = repo.get_repo_config("r1")
        assert result["status"] == "SYNC_OK"
        assert result["lastSyncAt"] == "2025-01-15T23:59:00Z"

    def test_update_sync_status_without_timestamp(self, repo):
        repo.put_repo_config("r1", {"name": "repo-1", "provider": "github", "status": "ACTIVE"})
        repo.update_repo_sync_status("r1", "SYNC_ERROR")

        result = repo.get_repo_config("r1")
        assert result["status"] == "SYNC_ERROR"


# ------------------------------------------------------------------
# 2. User-Git mappings
# ------------------------------------------------------------------

class TestUserMappings:
    def test_put_and_list(self, repo):
        repo.put_user_mapping("u1", {
            "provider": "github",
            "gitUsername": "dev-john",
            "gitEmail": "john@example.com",
            "createdAt": "2025-01-15T10:00:00Z",
            "createdBy": "admin-1",
        })
        repo.put_user_mapping("u1", {
            "provider": "gitlab",
            "gitUsername": "john-gl",
            "createdAt": "2025-01-15T10:00:00Z",
            "createdBy": "admin-1",
        })

        mappings = repo.list_user_mappings("u1")
        assert len(mappings) == 2
        providers = {m["provider"] for m in mappings}
        assert providers == {"github", "gitlab"}

    def test_list_empty(self, repo):
        assert repo.list_user_mappings("no-user") == []

    def test_delete_mapping(self, repo):
        repo.put_user_mapping("u1", {"provider": "github", "gitUsername": "dev-john"})
        repo.delete_user_mapping("u1", "github", "dev-john")
        assert repo.list_user_mappings("u1") == []

    def test_get_all_mappings_for_provider(self, repo):
        repo.put_user_mapping("u1", {"provider": "github", "gitUsername": "dev-john"})
        repo.put_user_mapping("u2", {"provider": "github", "gitUsername": "dev-jane"})
        repo.put_user_mapping("u3", {"provider": "gitlab", "gitUsername": "dev-bob"})

        github_mappings = repo.get_all_mappings_for_provider("github")
        assert len(github_mappings) == 2
        usernames = {m["gitUsername"] for m in github_mappings}
        assert usernames == {"dev-john", "dev-jane"}


# ------------------------------------------------------------------
# 3. Git activities (commits, PRs, reviews)
# ------------------------------------------------------------------

class TestBatchPutCommits:
    def test_batch_put_and_query(self, repo):
        commits = [
            {
                "date": "2025-01-15",
                "commitHash": "abc123",
                "repoId": "r1",
                "repository": "org/repo",
                "message": "feat: add auth",
                "filesChanged": 5,
                "linesAdded": 120,
                "linesRemoved": 30,
                "authorDate": "2025-01-15T14:30:00Z",
            },
            {
                "date": "2025-01-16",
                "commitHash": "def456",
                "repoId": "r1",
                "repository": "org/repo",
                "message": "fix: typo",
                "filesChanged": 1,
                "linesAdded": 2,
                "linesRemoved": 2,
                "authorDate": "2025-01-16T09:00:00Z",
            },
        ]
        count = repo.batch_put_commits("u1", commits)
        assert count == 2

        result = repo.query_commits("u1")
        assert len(result["items"]) == 2
        assert result["nextToken"] is None

    def test_query_with_date_range(self, repo):
        for day in range(10, 20):
            repo.batch_put_commits("u1", [{
                "date": f"2025-01-{day}",
                "commitHash": f"hash{day}",
                "repoId": "r1",
                "repository": "org/repo",
                "message": f"commit {day}",
                "authorDate": f"2025-01-{day}T10:00:00Z",
            }])

        result = repo.query_commits("u1", start_date="2025-01-12", end_date="2025-01-15")
        dates = {item["SK"].split("#")[1] for item in result["items"]}
        for d in dates:
            assert "2025-01-12" <= d <= "2025-01-15"


class TestBatchPutPullRequests:
    def test_batch_put_and_query(self, repo):
        prs = [
            {
                "date": "2025-01-14",
                "prId": "pr-1",
                "repoId": "r1",
                "repository": "org/repo",
                "title": "feat: add auth",
                "state": "merged",
                "createdAt": "2025-01-14T09:00:00Z",
                "mergedAt": "2025-01-14T15:30:00Z",
                "commitsCount": 3,
                "reviewsCount": 2,
            },
        ]
        count = repo.batch_put_pull_requests("u1", prs)
        assert count == 1

        result = repo.query_pull_requests("u1")
        assert len(result["items"]) == 1
        assert result["items"][0]["title"] == "feat: add auth"
        assert result["items"][0]["state"] == "merged"


class TestBatchPutReviews:
    def test_batch_put_and_query(self, repo):
        reviews = [
            {
                "date": "2025-01-15",
                "reviewId": "rev-1",
                "repoId": "r1",
                "repository": "org/repo",
                "prId": "pr-1",
                "reviewType": "APPROVED",
                "createdAt": "2025-01-15T10:00:00Z",
            },
        ]
        count = repo.batch_put_reviews("u1", reviews)
        assert count == 1

        result = repo.query_reviews("u1")
        assert len(result["items"]) == 1
        assert result["items"][0]["reviewType"] == "APPROVED"


class TestQueryPagination:
    def test_commits_pagination(self, repo):
        # Insert more items than the limit
        for i in range(5):
            repo.batch_put_commits("u1", [{
                "date": f"2025-01-{10 + i}",
                "commitHash": f"hash{i}",
                "repoId": "r1",
                "repository": "org/repo",
                "message": f"commit {i}",
                "authorDate": f"2025-01-{10 + i}T10:00:00Z",
            }])

        # Query with small limit
        result = repo.query_commits("u1", limit=2)
        assert len(result["items"]) == 2
        assert result["nextToken"] is not None

        # Fetch next page
        result2 = repo.query_commits("u1", limit=2, next_token=result["nextToken"])
        assert len(result2["items"]) == 2

    def test_pull_requests_pagination(self, repo):
        for i in range(4):
            repo.batch_put_pull_requests("u1", [{
                "date": f"2025-01-{10 + i}",
                "prId": f"pr-{i}",
                "repoId": "r1",
                "repository": "org/repo",
                "title": f"PR {i}",
                "state": "open",
                "createdAt": f"2025-01-{10 + i}T10:00:00Z",
            }])

        result = repo.query_pull_requests("u1", limit=2)
        assert len(result["items"]) == 2
        assert result["nextToken"] is not None


# ------------------------------------------------------------------
# 4. Sync stats
# ------------------------------------------------------------------

class TestSyncStats:
    def test_put_sync_stats(self, repo, table):
        stats = {
            "commitsCount": 45,
            "prsCount": 12,
            "reviewsCount": 18,
            "duration": 32,
            "status": "SUCCESS",
        }
        result = repo.put_sync_stats("r1", "2025-01-15T23:59:00Z", stats)

        assert result["PK"] == "GITREPO#r1"
        assert result["SK"] == "SYNC#2025-01-15T23:59:00Z"
        assert result["commitsCount"] == 45

        # Verify directly in DynamoDB
        raw = table.get_item(
            Key={"PK": "GITREPO#r1", "SK": "SYNC#2025-01-15T23:59:00Z"}
        ).get("Item")
        assert raw is not None
        assert raw["status"] == "SUCCESS"
