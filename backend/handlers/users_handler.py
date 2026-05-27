"""Handlers for Cognito user management endpoints.

GET    /api/users              — list users (with group info)
POST   /api/users              — create user (send invite by email)
PUT    /api/users/{userId}     — toggle admin role
DELETE /api/users/{userId}     — permanently delete user
"""

import os

import boto3


def _get_cognito_client(cognito_client=None):
    """Return the provided client or create a new CognitoIdentityProvider client."""
    return cognito_client or boto3.client("cognito-idp")


def _get_user_groups(client, user_pool_id: str, username: str) -> list[str]:
    """Get the list of group names a user belongs to."""
    try:
        resp = client.admin_list_groups_for_user(
            UserPoolId=user_pool_id,
            Username=username,
        )
        return [g["GroupName"] for g in resp.get("Groups", [])]
    except Exception:
        return []


def _map_user(cognito_user: dict, groups: list[str] | None = None) -> dict:
    """Map a Cognito user record to a simplified dict."""
    attributes = {
        attr["Name"]: attr["Value"]
        for attr in cognito_user.get("Attributes", [])
    }
    result = {
        "username": cognito_user.get("Username", ""),
        "email": attributes.get("email", ""),
        "kiroUserId": attributes.get("custom:kiro_user_id", ""),
        "status": cognito_user.get("UserStatus", ""),
        "enabled": cognito_user.get("Enabled", False),
        "createdAt": cognito_user.get("UserCreateDate", "").isoformat()
        if hasattr(cognito_user.get("UserCreateDate", ""), "isoformat")
        else str(cognito_user.get("UserCreateDate", "")),
    }
    if groups is not None:
        result["isAdmin"] = "Admins" in groups
    return result


def handle_list_users(cognito_client=None) -> dict:
    """Handle GET /api/users — list all Cognito users with group info."""
    client = _get_cognito_client(cognito_client)
    user_pool_id = os.environ.get("USER_POOL_ID", "")

    users = []
    params = {"UserPoolId": user_pool_id}

    while True:
        response = client.list_users(**params)
        for u in response.get("Users", []):
            username = u.get("Username", "")
            groups = _get_user_groups(client, user_pool_id, username)
            users.append(_map_user(u, groups))
        pagination_token = response.get("PaginationToken")
        if not pagination_token:
            break
        params["PaginationToken"] = pagination_token

    return {"users": users}


def handle_create_user(body: dict, cognito_client=None) -> dict:
    """Handle POST /api/users — create a new Cognito user."""
    client = _get_cognito_client(cognito_client)
    user_pool_id = os.environ.get("USER_POOL_ID", "")

    email = body.get("email", "").strip()
    if not email:
        return {"status": "error", "message": "email is required"}

    role = body.get("role", "user")
    kiro_user_id = (body.get("kiroUserId") or "").strip()

    try:
        user_attributes = [
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ]
        if kiro_user_id:
            user_attributes.append({"Name": "custom:kiro_user_id", "Value": kiro_user_id})

        response = client.admin_create_user(
            UserPoolId=user_pool_id,
            Username=email,
            UserAttributes=user_attributes,
            DesiredDeliveryMediums=["EMAIL"],
        )
        user = response.get("User", {})

        if role == "admin":
            try:
                client.admin_add_user_to_group(
                    UserPoolId=user_pool_id,
                    Username=email,
                    GroupName="Admins",
                )
            except Exception:
                pass

        groups = _get_user_groups(client, user_pool_id, email)
        return {
            "status": "created",
            "user": _map_user(user, groups),
        }
    except client.exceptions.UsernameExistsException:
        return {"status": "error", "message": f"User with email '{email}' already exists"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def handle_toggle_role(user_id: str, body: dict, caller_username: str, cognito_client=None) -> dict:
    """Handle PUT /api/users/{userId} — update user role and/or Kiro identity.

    Args:
        user_id: The username of the user to update.
        body: Request body with optional ``isAdmin`` (bool) and ``kiroUserId`` (str).
        caller_username: The username of the caller.
    """
    if user_id == caller_username:
        return {"status": "error", "message": "You cannot change your own role."}

    client = _get_cognito_client(cognito_client)
    user_pool_id = os.environ.get("USER_POOL_ID", "")

    is_admin = body.get("isAdmin")
    kiro_user_id = body.get("kiroUserId")

    try:
        # Update admin group membership if specified
        if is_admin is not None:
            if is_admin:
                client.admin_add_user_to_group(
                    UserPoolId=user_pool_id,
                    Username=user_id,
                    GroupName="Admins",
                )
            else:
                client.admin_remove_user_from_group(
                    UserPoolId=user_pool_id,
                    Username=user_id,
                    GroupName="Admins",
                )

        # Update kiroUserId custom attribute if specified
        if kiro_user_id is not None:
            client.admin_update_user_attributes(
                UserPoolId=user_pool_id,
                Username=user_id,
                UserAttributes=[
                    {"Name": "custom:kiro_user_id", "Value": kiro_user_id},
                ],
            )

        result = {"status": "updated", "userId": user_id}
        if is_admin is not None:
            result["isAdmin"] = is_admin
        if kiro_user_id is not None:
            result["kiroUserId"] = kiro_user_id
        return result
    except client.exceptions.UserNotFoundException:
        return {"status": "error", "message": f"User '{user_id}' not found"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def handle_delete_user(user_id: str, caller_username: str, cognito_client=None) -> dict:
    """Handle DELETE /api/users/{userId} — permanently delete a Cognito user."""
    if user_id == caller_username:
        return {"status": "error", "message": "You cannot delete your own account."}

    client = _get_cognito_client(cognito_client)
    user_pool_id = os.environ.get("USER_POOL_ID", "")

    try:
        client.admin_delete_user(
            UserPoolId=user_pool_id,
            Username=user_id,
        )
        return {"status": "deleted", "userId": user_id}
    except client.exceptions.UserNotFoundException:
        return {"status": "error", "message": f"User '{user_id}' not found"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
