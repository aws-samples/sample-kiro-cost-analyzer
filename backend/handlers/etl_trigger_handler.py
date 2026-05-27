"""Handler for POST /api/etl/trigger — trigger manual ETL execution via Step Functions."""

import os

import boto3


def _get_sfn_client(sfn_client=None):
    """Return the provided client or create a new Step Functions client."""
    return sfn_client or boto3.client("stepfunctions")


def handle_etl_trigger(sfn_client=None) -> dict:
    """Handle POST /api/etl/trigger — start Step Functions execution.

    Starts a new execution of the ETL State Machine so it runs
    in the background without blocking the API response.

    Args:
        sfn_client: Optional pre-configured Step Functions client for testing.

    Returns:
        Dict with status 'triggered' and the execution ARN.
    """
    client = _get_sfn_client(sfn_client)
    state_machine_arn = os.environ.get("STATE_MACHINE_ARN", "")

    if not state_machine_arn:
        return {
            "status": "error",
            "message": "STATE_MACHINE_ARN environment variable is not configured",
        }

    response = client.start_execution(
        stateMachineArn=state_machine_arn,
        input="{}",
    )

    return {
        "status": "triggered",
        "executionId": response.get("executionArn", state_machine_arn),
    }
