"""Tests for backend.handler routing of the Git mapping DELETE route.

Focus (task 6.4, Requirement 2.11): the mapping delete route was shortened
from a three-segment path (``{userId}/{provider}/{gitUsername}``) to a
two-segment path (``{userId}/{provider}``). These tests confirm the router
dispatches the new two-segment path with exactly two captured groups, and
that the old three-segment path no longer matches
``_GIT_MAPPING_DELETE_PATTERN`` at all (falling through to this router's
standard unmatched-route behavior, a 404 ``NotFound``).
"""

import json
from unittest.mock import patch

from backend.handler import lambda_handler


def _make_event(
    method: str = "GET",
    path: str = "/api/git/mappings",
    query_params: dict | None = None,
    body: dict | None = None,
    groups: str = "Admins",
    sub: str = "admin-1",
    username: str = "admin-1",
) -> dict:
    """Build a minimal API Gateway proxy event, admin by default."""
    event = {
        "httpMethod": method,
        "path": path,
        "queryStringParameters": query_params,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": sub,
                    "cognito:username": username,
                    "cognito:groups": groups,
                }
            }
        },
    }
    return event


class TestGitMappingDeleteRoute:
    @patch("backend.handler.git_mapping_handler")
    def test_two_segment_path_dispatches_with_user_id_and_provider(self, mock_mod):
        mock_mod.handle_delete_mapping.return_value = {
            "userId": "user-1",
            "provider": "gitlab",
            "deleted": True,
        }

        event = _make_event("DELETE", "/api/git/mappings/user-1/gitlab")
        resp = lambda_handler(event, None)

        assert resp["statusCode"] == 200
        # Exactly two captured groups reach the handler: (userId, provider).
        mock_mod.handle_delete_mapping.assert_called_once_with("user-1", "gitlab")
        body = json.loads(resp["body"])
        assert body == {"userId": "user-1", "provider": "gitlab", "deleted": True}

    @patch("backend.handler.git_mapping_handler")
    def test_old_three_segment_path_no_longer_matches_falls_through_to_404(
        self, mock_mod
    ):
        event = _make_event(
            "DELETE", "/api/git/mappings/user-1/gitlab/some-git-username"
        )
        resp = lambda_handler(event, None)

        assert resp["statusCode"] == 404
        body = json.loads(resp["body"])
        assert body["error"] == "NotFound"
        mock_mod.handle_delete_mapping.assert_not_called()

    @patch("backend.handler.git_mapping_handler")
    def test_non_admin_gets_403_and_handler_not_called(self, mock_mod):
        event = _make_event(
            "DELETE", "/api/git/mappings/user-1/gitlab", groups="Viewers"
        )
        resp = lambda_handler(event, None)

        assert resp["statusCode"] == 403
        mock_mod.handle_delete_mapping.assert_not_called()
