"""Integration tests: UC-005-MAIN-MCP-02 authentication optional for discovery.

Covers:
- UC-005-MAIN-MCP-02: Authentication optional for discovery
- UC-005-EXT-A-01: Tenant resolution failure returns TENANT_REQUIRED error

The list_creative_formats endpoint is a discovery/catalog endpoint.
While tenant context is required to resolve the format catalog, an
explicit auth *token* should not be required. A buyer can discover
formats without presenting credentials as long as tenant context
is available.
"""

from __future__ import annotations

import pytest

from src.core.schemas import Format, FormatId, ListCreativeFormatsResponse
from tests.factories import PrincipalFactory, TenantFactory
from tests.harness import CreativeFormatsEnv
from tests.harness.transport import Transport

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

DEFAULT_AGENT_URL = "https://creative.adcontextprotocol.org"


def _make_format(format_id: str, name: str) -> Format:
    """Build a minimal Format for testing."""
    return Format(
        format_id=FormatId(agent_url=DEFAULT_AGENT_URL, id=format_id),
        name=name,
        type="display",
        is_standard=True,
    )


# ---------------------------------------------------------------------------
# UC-005-MAIN-MCP-02: Authentication optional for discovery
# ---------------------------------------------------------------------------


class TestAuthOptionalForDiscovery:
    """Covers: UC-005-MAIN-MCP-02 -- auth token not required for format discovery."""

    def test_impl_returns_formats_with_no_auth_token(self, integration_db):
        """UC-005-MAIN-MCP-02: _impl succeeds when identity has no auth_token.

        Given an identity with tenant context but auth_token=None,
        When calling _list_creative_formats_impl,
        Then the response is a valid ListCreativeFormatsResponse with formats.
        """
        formats = [
            _make_format("fmt_1", "Display Banner"),
            _make_format("fmt_2", "Leaderboard"),
        ]

        with CreativeFormatsEnv() as env:
            TenantFactory(tenant_id="test_tenant")
            env.set_registry_formats(formats)

            identity_no_token = PrincipalFactory.make_identity(
                principal_id="anon_buyer",
                tenant_id="test_tenant",
            )
            response = env.call_impl(identity=identity_no_token)

        assert isinstance(response, ListCreativeFormatsResponse)
        assert len(response.formats) == 2
        ids = {f.format_id.id for f in response.formats}
        assert ids == {"fmt_1", "fmt_2"}

    def test_a2a_returns_formats_with_no_auth_token(self, integration_db):
        """UC-005-MAIN-MCP-02: A2A wrapper succeeds without auth_token.

        Given an identity with tenant context but auth_token=None,
        When calling list_creative_formats_raw (A2A),
        Then the response is a valid ListCreativeFormatsResponse.
        """
        formats = [_make_format("a2a_fmt", "A2A Display")]

        with CreativeFormatsEnv() as env:
            TenantFactory(tenant_id="test_tenant")
            env.set_registry_formats(formats)

            identity_no_token = PrincipalFactory.make_identity(
                principal_id="anon_buyer",
                tenant_id="test_tenant",
            )
            response = env.call_a2a(identity=identity_no_token)

        assert isinstance(response, ListCreativeFormatsResponse)
        assert len(response.formats) == 1
        assert response.formats[0].format_id.id == "a2a_fmt"

    def test_a2a_with_no_auth_token_via_call_via(self, integration_db):
        """UC-005-MAIN-MCP-02: call_via(A2A) with explicit no-token identity.

        Verifies A2A transport dispatch succeeds without auth token.
        """
        formats = [_make_format("a2a_dispatch", "A2A Dispatch Format")]

        with CreativeFormatsEnv() as env:
            TenantFactory(tenant_id="test_tenant")
            env.set_registry_formats(formats)

            identity_no_token = PrincipalFactory.make_identity(
                principal_id="anon_buyer",
                tenant_id="test_tenant",
            )
            result = env.call_via(Transport.A2A, identity=identity_no_token)

        assert result.is_success
        assert isinstance(result.payload, ListCreativeFormatsResponse)
        assert len(result.payload.formats) == 1

    # (Deleted) test_no_tenant_context_raises_auth_error: it built an identity with a
    # resolved principal and tenant=None. See the note on the deleted
    # TestTenantResolutionFailure class below -- the state is unreachable and the
    # behavior it expected is not the one production has.

    def test_authenticated_vs_unauthenticated_return_same_catalog(self, integration_db):
        """UC-005-MAIN-MCP-02: auth token does not affect the catalog returned.

        Both an authenticated and unauthenticated identity with the same
        tenant context should receive identical format catalogs.
        """
        formats = [
            _make_format("shared_1", "Shared Format 1"),
            _make_format("shared_2", "Shared Format 2"),
        ]

        with CreativeFormatsEnv() as env:
            TenantFactory(tenant_id="test_tenant")
            env.set_registry_formats(formats)

            authed_identity = PrincipalFactory.make_identity(
                principal_id="authed_buyer",
                tenant_id="test_tenant",
            )
            unauthed_identity = PrincipalFactory.make_identity(
                principal_id="anon_buyer",
                tenant_id="test_tenant",
            )

            authed_response = env.call_impl(identity=authed_identity)
            unauthed_response = env.call_impl(identity=unauthed_identity)

        assert len(authed_response.formats) == len(unauthed_response.formats)
        authed_ids = {f.format_id.id for f in authed_response.formats}
        unauthed_ids = {f.format_id.id for f in unauthed_response.formats}
        assert authed_ids == unauthed_ids


# ---------------------------------------------------------------------------
# UC-005-EXT-A-01: Tenant resolution failure
# ---------------------------------------------------------------------------


# (Deleted) TestTenantResolutionFailure, whose two tests -- an in-process AUTH_MISSING
# raise and its A2A wire envelope -- both began by constructing an identity with a
# RESOLVED principal and ``tenant=None``.
#
# That state cannot be produced. ``_resolve_identity`` looks a credential up only inside
# the tenant the request reached ("no tenant, no lookup", step 4), so a caller with no
# tenant has no principal either; and ``ResolvedIdentity`` declares ``tenant`` required,
# which is why these calls now fail in ``make_identity`` rather than in the assertion.
#
# The reachable tenant-less discovery request is the anonymous one --
# ``PublicIdentity(principal=None, tenant=None)`` -- and production answers it with an
# empty catalog rather than refusing it: "No seller is addressed: there are no formats to
# list, and nothing to refuse" (``_list_creative_formats_impl``, 76c2a96fb, which replaced
# the ``require_tenant`` raise these tests were written against).
#
# So UC-005-EXT-A-01 ("no hostname mapping resolves to a tenant -> error") is now
# UNGRADED. Grading it means driving the boundary with no ``x-adcp-tenant`` header and
# reading the wire; that also settles whether the empty catalog or the refusal is the
# spec-correct answer, which is a question for the storyboard, not for a fixture.
