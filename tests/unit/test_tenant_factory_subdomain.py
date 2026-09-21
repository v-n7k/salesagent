"""Tests for TenantFactory subdomain derivation.

Regression coverage for the split-brain subdomain bug (#1418): the ORM
``TenantFactory.subdomain`` LazyAttribute and the ``make_tenant()``
``TenantContext`` must derive the subdomain identically, because the persisted
row and the identity a test hands a tool have to name the same tenant.

The third derivation these tests used to grade — the value the e2e_rest
dispatcher sends as ``x-adcp-tenant`` — no longer exists. ``credential()``
(``tests/harness/_base.py``) sends the raw ``tenant_id`` on every leg, and
``_detect_tenant`` tries it as a subdomain before taking it as the literal id,
so the wire carries no derived subdomain to disagree with the row.
"""

from __future__ import annotations


class TestTenantSubdomainDerivation:
    """The ORM row and the identity's TenantContext derive one subdomain."""

    def test_orm_row_matches_make_tenant_for_underscore_id(self):
        """ORM-row subdomain == make_tenant TenantContext subdomain.

        TenantFactory.build() evaluates the same subdomain LazyAttribute that is
        persisted to the DB row, so its value is the authoritative ORM-row value.
        Two separate call sites of ``tenant_subdomain`` — re-inlining a derivation
        at either one is what this catches.
        """
        from tests.factories.core import TenantFactory

        tenant_id = "test_tenant"
        orm_subdomain = TenantFactory.build(tenant_id=tenant_id).subdomain
        identity_subdomain = TenantFactory.make_tenant(tenant_id).subdomain

        assert orm_subdomain == identity_subdomain

    def test_subdomain_has_no_underscores_for_underscore_id(self):
        """Derived subdomain is hyphen-safe (no underscores).

        Subdomains feed publisher_domain (``f"{subdomain}.example.com"``), and the
        AdCP domain pattern rejects underscores, so an underscore tenant_id must
        produce a hyphen-only subdomain.
        """
        from tests.factories.core import TenantFactory

        orm_subdomain = TenantFactory.build(tenant_id="test_tenant").subdomain

        assert "_" not in orm_subdomain
