"""Regression tests for salesagent-rldj (C4: version negotiation + idempotency posture).

Pins the CORE behavior from the refined implementation plan, steps 1-4:

1. ``SUPPORTED_ADCP_VERSIONS`` (new ``src/core/version_negotiation.py``) is
   derived from ``adcp.get_adcp_spec_version()`` STRIPPED to release
   precision (MAJOR.MINOR, e.g. "3.1"), never the raw 3-part semver
   ("3.1.1") which violates the v3.1.1 ``supported_versions`` wire pattern
   (``^\\d+\\.\\d+(-...)?$``).
2. ``negotiate_adcp_version()`` raises the new ``AdCPVersionUnsupportedError``
   (-> wire code ``VERSION_UNSUPPORTED``) for a version pin outside
   ``SUPPORTED_ADCP_VERSIONS``, and is a no-op for a supported pin / None.
3. Negotiation runs at the BOUNDARY, so it covers every tool and stays
   un-tenant-gated. It used to run inside ``_get_adcp_capabilities_impl``,
   which left every other tool serving a buyer whose pin this build cannot
   speak. The wire-level grading across transports lives in
   ``tests/integration/test_version_negotiation_wire.py``.
4. The DRY ``_build_adcp_block()`` helper derives ``supported_versions`` from
   the single-sourced constant on BOTH the minimal (no-tenant) and full
   (tenant-resolved) response paths -- no literal duplication.

Does NOT cover plan step 5 (harness override seam) or step 6 (BDD step
authoring) -- that is separate implementation-atom scope.
"""

from __future__ import annotations

import re

import pytest

from src.core.schemas import GetAdcpCapabilitiesRequest
from tests.factories.principal import PrincipalFactory


class TestSupportedAdcpVersionsDerivation:
    """Plan step 1: SUPPORTED_ADCP_VERSIONS must be release-precision, derived."""

    def test_supported_adcp_versions_are_release_precision(self):
        """Every entry must match the v3.1.1 SupportedVersion wire pattern
        (release precision, i.e. MAJOR.MINOR only -- NOT MAJOR.MINOR.PATCH).

        adcp.get_adcp_spec_version() returns "3.1.1" today (verified via
        direct interpreter check per salesagent-rldj notes) -- a raw
        pass-through would produce "3.1.1", which FAILS this pattern.
        """
        from src.core.version_negotiation import SUPPORTED_ADCP_VERSIONS

        release_precision_pattern = re.compile(r"^\d+\.\d+(-[a-zA-Z0-9.-]+)?$")
        assert len(SUPPORTED_ADCP_VERSIONS) >= 1
        for version in SUPPORTED_ADCP_VERSIONS:
            assert release_precision_pattern.match(version), (
                f"{version!r} is not release-precision (MAJOR.MINOR) -- "
                "did SUPPORTED_ADCP_VERSIONS pass the raw semver through unstripped?"
            )

    def test_supported_adcp_versions_derived_from_installed_sdk_stripped_to_release(self):
        """Pins the EXACT derivation: strip adcp.get_adcp_spec_version() to
        its first two dot-separated components, not a hardcoded literal.
        """
        import adcp

        from src.core.version_negotiation import SUPPORTED_ADCP_VERSIONS

        full_spec_version = adcp.get_adcp_spec_version()
        expected_release = ".".join(full_spec_version.split(".")[:2])

        assert expected_release in SUPPORTED_ADCP_VERSIONS


class TestNegotiateAdcpVersion:
    """Plan step 1: negotiate_adcp_version() raises for unsupported pins."""

    def test_rejects_unsupported_version_pin(self):
        from src.core.exceptions import AdCPVersionUnsupportedError
        from src.core.version_negotiation import negotiate_adcp_version

        with pytest.raises(AdCPVersionUnsupportedError) as exc_info:
            negotiate_adcp_version("0.1", None)

        err = exc_info.value
        assert err.error_code == "VERSION_UNSUPPORTED"
        assert err.status_code == 400

    def test_accepts_supported_version_pin_as_noop(self):
        from src.core.version_negotiation import SUPPORTED_ADCP_VERSIONS, negotiate_adcp_version

        supported = SUPPORTED_ADCP_VERSIONS[0]
        # Must not raise.
        assert negotiate_adcp_version(supported, None) is None

    def test_no_pin_requested_is_noop(self):
        from src.core.version_negotiation import negotiate_adcp_version

        # Buyer sent no version/major pin at all -- must not raise.
        assert negotiate_adcp_version(None, None) is None

    def test_a_supported_major_does_not_excuse_an_unsupported_release(self):
        """The pins are constraints, not alternatives.

        Read as alternatives, a request pinning an unsupported RELEASE alongside a
        supported MAJOR was accepted -- the major check returned before the release was
        ever judged.
        """
        from src.core.exceptions import AdCPVersionUnsupportedError
        from src.core.version_negotiation import SUPPORTED_ADCP_MAJORS, negotiate_adcp_version

        with pytest.raises(AdCPVersionUnsupportedError):
            negotiate_adcp_version("99.0", SUPPORTED_ADCP_MAJORS[0])

    def test_a_supported_release_does_not_excuse_an_unsupported_major(self):
        from src.core.exceptions import AdCPVersionUnsupportedError
        from src.core.version_negotiation import SUPPORTED_ADCP_VERSIONS, negotiate_adcp_version

        with pytest.raises(AdCPVersionUnsupportedError):
            negotiate_adcp_version(SUPPORTED_ADCP_VERSIONS[0], 99)

    def test_the_refusal_names_the_supported_majors(self):
        """A buyer refused on a MAJOR needs the majors, not only the releases."""
        from src.core.exceptions import AdCPVersionUnsupportedError
        from src.core.version_negotiation import (
            SUPPORTED_ADCP_MAJORS,
            SUPPORTED_ADCP_VERSIONS,
            negotiate_adcp_version,
        )

        with pytest.raises(AdCPVersionUnsupportedError) as exc_info:
            negotiate_adcp_version(None, 99)

        details = exc_info.value.details
        assert details.supported_versions == SUPPORTED_ADCP_VERSIONS
        assert details.supported_majors == SUPPORTED_ADCP_MAJORS
        assert details.adcp_major_version == 99

    def test_pins_naming_different_majors_are_refused(self, monkeypatch):
        """Two individually-supported pins can still contradict each other.

        Unreachable while this seller speaks one release -- a supported release and a
        supported major necessarily agree -- so the supported set is widened here to reach
        the branch. It becomes reachable for real the moment a second major is served,
        which is exactly when nobody would think to add the rule.
        """
        from src.core import version_negotiation
        from src.core.exceptions import AdCPVersionUnsupportedError

        monkeypatch.setattr(version_negotiation, "SUPPORTED_ADCP_VERSIONS", ["3.1", "4.0"])
        monkeypatch.setattr(version_negotiation, "SUPPORTED_ADCP_MAJORS", [3, 4])

        # Each pin is supported on its own; together they name no release that exists.
        with pytest.raises(AdCPVersionUnsupportedError):
            version_negotiation.negotiate_adcp_version("3.1", 4)

        # The aligned pairs stay acceptable.
        assert version_negotiation.negotiate_adcp_version("3.1", 3) is None
        assert version_negotiation.negotiate_adcp_version("4.0", 4) is None


class TestBoundaryNegotiatesForEveryTool:
    """Plan step 3: negotiation is the boundary's, so no tool can skip it.

    ``_get_adcp_capabilities_impl`` no longer negotiates. That the boundary refuses a bad
    pin is graded on the wire by BR-PROTOCOL-001 and BR-UC-010's adcp_version scenarios;
    this class keeps only the implementation-level half.
    """

    async def test_capabilities_impl_no_longer_negotiates_on_its_own(self):
        """The call site MOVED; it was not duplicated.

        Two negotiators would drift, and the boundary's is the one every tool crosses.
        """
        from src.core.tools.capabilities import _get_adcp_capabilities_impl

        req = GetAdcpCapabilitiesRequest(adcp_version="0.1")

        # Reached directly, past the boundary, the implementation just answers. The
        # caller is anonymous and names no seller: a PublicIdentity with neither.
        response = _get_adcp_capabilities_impl(req, PrincipalFactory.make_public_identity(tenant=None))
        assert response.adcp.supported_versions is not None


class TestBuildAdcpBlockDry:
    """Plan step 3-4: _build_adcp_block() single-sources supported_versions
    across BOTH the no-tenant minimal response and the tenant-resolved full
    response -- no literal Adcp(...) duplication.
    """

    def test_minimal_no_tenant_response_declares_derived_supported_versions(self):
        from src.core.tools.capabilities import _get_adcp_capabilities_impl
        from src.core.version_negotiation import SUPPORTED_ADCP_VERSIONS

        response = _get_adcp_capabilities_impl(None, PrincipalFactory.make_public_identity(tenant=None))

        assert response.adcp.supported_versions is not None
        assert [v.root for v in response.adcp.supported_versions] == SUPPORTED_ADCP_VERSIONS

    def test_full_tenant_response_declares_same_derived_supported_versions(self):
        from src.core.tools.capabilities import _get_adcp_capabilities_impl
        from src.core.version_negotiation import SUPPORTED_ADCP_VERSIONS
        from tests.unit.test_get_adcp_capabilities import (
            _make_capabilities_identity,
            _patch_capabilities_deps,
        )

        identity = _make_capabilities_identity(principal_id=None, tenant_id="test-tenant-version-negotiation")

        with _patch_capabilities_deps(adapter=None):
            response = _get_adcp_capabilities_impl(None, identity)

        assert response.adcp.supported_versions is not None
        assert [v.root for v in response.adcp.supported_versions] == SUPPORTED_ADCP_VERSIONS
