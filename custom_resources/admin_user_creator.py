"""
CloudFormation Custom Resource Lambda for creating the initial admin user
in Cognito User Pool during stack deployment.

Handles Create, Update, and Delete lifecycle events.
"""

import json
import logging
import urllib.parse
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

cognito = boto3.client("cognito-idp")

ADMIN_GROUP_NAME = "Admins"


def lambda_handler(event, context):
    """Entry point for CloudFormation Custom Resource."""
    logger.info("Received event: %s", json.dumps(event))

    request_type = event["RequestType"]
    properties = event["ResourceProperties"]
    user_pool_id = properties["UserPoolId"]
    admin_email = properties["AdminEmail"]

    try:
        if request_type == "Create":
            _ensure_admin_group(user_pool_id)
            _create_admin_user(user_pool_id, admin_email)
            _add_user_to_group(user_pool_id, admin_email)
            _send_response(event, context, "SUCCESS", {"Message": "Admin user created"})

        elif request_type == "Update":
            _ensure_admin_group(user_pool_id)
            _send_response(event, context, "SUCCESS", {"Message": "No-op on update"})

        elif request_type == "Delete":
            _send_response(event, context, "SUCCESS", {"Message": "No-op on delete"})

        else:
            _send_response(event, context, "FAILED", {"Message": f"Unknown RequestType: {request_type}"})

    except Exception as e:
        logger.error("Error handling %s: %s", request_type, str(e))
        _send_response(event, context, "FAILED", {"Message": str(e)})


def _ensure_admin_group(user_pool_id: str) -> None:
    """Create the Admins group if it doesn't already exist."""
    try:
        cognito.create_group(
            GroupName=ADMIN_GROUP_NAME,
            UserPoolId=user_pool_id,
            Description="Administrator group with full access",
        )
        logger.info("Created group '%s'", ADMIN_GROUP_NAME)
    except cognito.exceptions.GroupExistsException:
        logger.info("Group '%s' already exists", ADMIN_GROUP_NAME)


def _create_admin_user(user_pool_id: str, email: str) -> None:
    """Create the admin user in Cognito. Sends a temporary password via email."""
    try:
        cognito.admin_create_user(
            UserPoolId=user_pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )
        logger.info("Created admin user '%s'", email)
    except cognito.exceptions.UsernameExistsException:
        logger.info("Admin user '%s' already exists", email)


def _add_user_to_group(user_pool_id: str, email: str) -> None:
    """Add the admin user to the Admins group."""
    cognito.admin_add_user_to_group(
        UserPoolId=user_pool_id,
        Username=email,
        GroupName=ADMIN_GROUP_NAME,
    )
    logger.info("Added user '%s' to group '%s'", email, ADMIN_GROUP_NAME)


def _send_response(event, context, status, data):
    """Send response back to CloudFormation."""
    response_url = event["ResponseURL"]

    # Validate URL scheme — only HTTPS is permitted for CloudFormation
    # custom resource callbacks (mitigates Bandit B310).
    parsed = urllib.parse.urlparse(response_url)
    if parsed.scheme != "https":
        raise ValueError(f"Refusing to send response to non-HTTPS URL: {parsed.scheme}")

    response_body = json.dumps({
        "Status": status,
        "Reason": data.get("Message", "See CloudWatch logs"),
        "PhysicalResourceId": event.get("PhysicalResourceId", context.log_stream_name),
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data,
    })

    logger.info("Sending response: %s", response_body)

    req = urllib.request.Request(
        url=response_url,
        data=response_body.encode("utf-8"),
        headers={"Content-Type": ""},
        method="PUT",
    )
    urllib.request.urlopen(req)  # noqa: S310 — URL scheme validated above
