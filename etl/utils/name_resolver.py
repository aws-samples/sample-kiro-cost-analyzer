"""Name resolver — wraps user_name_resolver for the ETL pipeline.

Provides a simplified interface for resolving a set of userIds to
(displayName, userName) tuples using the UserNamesTable cache and
IAM Identity Center fallback.
"""

from __future__ import annotations

import logging

try:
    from user_name_resolver import resolve_user_names
except ImportError:
    from etl.user_name_resolver import resolve_user_names

logger = logging.getLogger(__name__)


def resolve_names(
    user_ids: set[str],
    identity_store_id: str,
    table_name: str,
    dynamodb=None,
    identity_client=None,
) -> dict[str, tuple[str, str]]:
    """Resolve a batch of userIds to (displayName, userName).

    Delegates to :func:`etl.user_name_resolver.resolve_user_names` which:
    1. Checks the DynamoDB UserNamesTable cache first
    2. Falls back to IAM Identity Center ``DescribeUser`` for cache misses
    3. Caches new resolutions for future lookups

    Forwarding guarantee
    --------------------
    The ``identity_client`` parameter is forwarded to
    :func:`etl.user_name_resolver.resolve_user_names` **verbatim**, with no
    transformation, wrapping, or substitution. Whatever object (or ``None``)
    is passed in is the exact same reference the downstream resolver
    receives. In particular:

    - When ``identity_client`` is ``None`` (single-account mode), the
      downstream resolver builds a default ``boto3.client("identitystore")``.
    - When ``identity_client`` is a cross-account Identity Store client
      built via :func:`etl.sts_session.get_identity_store_client`, that
      exact client is used for every ``DescribeUser`` call — no new client
      is constructed here and no credential rewriting occurs.

    This transparency is what lets callers switch between single-account
    and cross-account mode by swapping the injected client only
    (Requirement 4.5).

    Parameters
    ----------
    user_ids:
        Set of userId strings (UUIDs) to resolve.
    identity_store_id:
        IAM Identity Center identity store ID.
    table_name:
        DynamoDB UserNamesTable name.
    dynamodb:
        Optional DynamoDB resource (for testing or cross-account wiring).
    identity_client:
        Optional Identity Center client. Forwarded verbatim to
        :func:`etl.user_name_resolver.resolve_user_names`; see the
        "Forwarding guarantee" section above.

    Returns
    -------
    dict mapping userId → (displayName, userName).
    Empty strings are returned for userIds that cannot be resolved.
    """
    if not user_ids:
        return {}

    if not identity_store_id or not table_name:
        logger.warning(
            "Name resolution skipped: identity_store_id=%s, table_name=%s",
            identity_store_id,
            table_name,
        )
        return {uid: ("", "") for uid in user_ids}

    try:
        return resolve_user_names(
            user_ids=user_ids,
            identity_store_id=identity_store_id,
            table_name=table_name,
            dynamodb=dynamodb,
            identity_client=identity_client,
        )
    except Exception:
        logger.warning("Failed to resolve user names", exc_info=True)
        return {uid: ("", "") for uid in user_ids}
