"""Tests for etl.utils.name_resolver module."""

from unittest.mock import MagicMock, patch

from etl.utils.name_resolver import resolve_names


class TestResolveNames:
    def test_empty_user_ids_returns_empty(self):
        result = resolve_names(set(), "store-id", "table-name")
        assert result == {}

    def test_missing_identity_store_returns_empty_names(self):
        result = resolve_names({"u1", "u2"}, "", "table-name")
        assert result == {"u1": ("", ""), "u2": ("", "")}

    def test_missing_table_name_returns_empty_names(self):
        result = resolve_names({"u1"}, "store-id", "")
        assert result == {"u1": ("", "")}

    @patch("etl.utils.name_resolver.resolve_user_names")
    def test_delegates_to_resolve_user_names(self, mock_resolve):
        mock_resolve.return_value = {"u1": ("Alice", "alice")}
        result = resolve_names({"u1"}, "store-id", "table-name")
        assert result == {"u1": ("Alice", "alice")}
        mock_resolve.assert_called_once_with(
            user_ids={"u1"},
            identity_store_id="store-id",
            table_name="table-name",
            dynamodb=None,
            identity_client=None,
        )

    @patch("etl.utils.name_resolver.resolve_user_names", side_effect=Exception("boom"))
    def test_exception_returns_empty_names(self, _mock):
        result = resolve_names({"u1", "u2"}, "store-id", "table-name")
        assert all(v == ("", "") for v in result.values())
        assert set(result.keys()) == {"u1", "u2"}

    @patch("etl.utils.name_resolver.resolve_user_names")
    def test_forwards_non_none_identity_client_verbatim(self, mock_resolve):
        """A non-None ``identity_client`` must be forwarded to
        ``resolve_user_names`` without any transformation, wrapping, or
        substitution (Requirement 4.5 — forwarding guarantee).
        """
        mock_resolve.return_value = {"u1": ("Alice", "alice")}
        injected_client = MagicMock(name="injected-identitystore-client")

        result = resolve_names(
            {"u1"},
            "store-id",
            "table-name",
            identity_client=injected_client,
        )

        assert result == {"u1": ("Alice", "alice")}
        mock_resolve.assert_called_once_with(
            user_ids={"u1"},
            identity_store_id="store-id",
            table_name="table-name",
            dynamodb=None,
            identity_client=injected_client,
        )
        # The exact same reference must have been forwarded — no wrapping.
        call_kwargs = mock_resolve.call_args.kwargs
        assert call_kwargs["identity_client"] is injected_client

    @patch("etl.utils.name_resolver.resolve_user_names")
    def test_forwards_dynamodb_and_identity_client_together(self, mock_resolve):
        """Both injection seams (``dynamodb`` and ``identity_client``) must be
        forwarded verbatim in a single call."""
        mock_resolve.return_value = {"u1": ("Alice", "alice")}
        injected_dynamodb = MagicMock(name="injected-dynamodb-resource")
        injected_client = MagicMock(name="injected-identitystore-client")

        resolve_names(
            {"u1"},
            "store-id",
            "table-name",
            dynamodb=injected_dynamodb,
            identity_client=injected_client,
        )

        call_kwargs = mock_resolve.call_args.kwargs
        assert call_kwargs["dynamodb"] is injected_dynamodb
        assert call_kwargs["identity_client"] is injected_client
