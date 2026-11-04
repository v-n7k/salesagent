"""Unit tests for SSRF-adjacent URL handling (F-04).

``TestCheckUrlSsrf`` and ``TestBlockedHostnames`` — the direct tests of
``check_url_ssrf``/``BLOCKED_HOSTNAMES`` — are DELETED. The module
``src.core.security.url_validator`` is GONE entirely: it first lost the SSRF
half (salesagent-tbrk.1 / GH #1802) — ``check_url_ssrf``, ``check_url_syntax``,
``BLOCKED_NETWORKS``, ``BLOCKED_HOSTNAMES`` — and its surviving reserved-TLD
family then moved to its one remaining owner,
``src.core.security.egress.policy`` (``RESERVED_TLDS`` /
``reserved_tld_for_host`` / ``is_reserved_tld_host``), which is where
``TestReservedTldPolicy`` below grades it. The policy VERDICT graded here is
unchanged by that move — only the import path is.
Every deleted row's behavioral content migrated into
``tests/integration/test_outbound_http.py``'s verdict-parity table (see that
file's ``EgressPolicy.check_registration`` cases), which grades the SAME
address predicate now shared by both the registration and dial verdicts —
triaged row-by-row so nothing was silently dropped:

- localhost / metadata / docker / gateway-docker hostname rows -> the
  blocked-hostname parity rows.
- loopback, RFC1918 x3, link-local, 224.0.0.1, ``[ff02::1]``,
  ``[64:ff9b::...]`` -> the reserved-range parity rows.
- CGNAT literal -> the supplement-range parity rows (this is the row that
  used to pass ONLY because ``url_validator.BLOCKED_NETWORKS`` covered it —
  now covered by the shared predicate on both verdicts, closing
  the gap recorded in #1792).
- non-http / file scheme / require_https -> the non-https parity rows.
- ``valid_public_https_url_accepted`` -> the accepted half of the
  unresolvable-hostname divergence case.
- ``test_unresolvable_hostname_rejected`` (the ``resolve_dns=True`` DNS
  branch — dropped as dead code, one production caller, always
  ``resolve_dns=False``) -> its live semantics are preserved by the DIAL half
  of that same divergence case: an unresolvable host IS refused, via the
  SDK's single pinned resolution.
- ``valid_public_http_url_accepted`` (``require_https=False``) -> genuinely
  dead; the one production caller always passed ``require_https=True``.
  Nothing to migrate.

One more class is RETIRED rather than migrated, and for a different reason —
its subject is gone too, but it had no address-policy content to move:

- ``TestValidateAgentUrl`` (7 rows) tested
  ``src.core.tools.media_buy_create.validate_agent_url``, a format-only
  (scheme + netloc) pre-check. That function no longer exists anywhere in
  ``src/``: ``media_buy_create`` now hands the creative-agent URL straight to
  the seam with ``CounterpartyUrl`` provenance
  (``media_buy_create.py`` lines 418 / 702 / 718), so the real verdict — not a
  structural guess — is what the buyer gets. A format-only accept is no longer
  a behavior this codebase has, so there is nothing to retarget; the refusal
  that replaced it is graded in
  ``tests/integration/test_creative_agent_url_ingest_refusal.py``.

Covers:
- reserved-TLD policy: the surviving half of the retired ``url_validator``, now
  owned by ``src.core.security.egress.policy``
  (RFC 9421 notification-proof policy — "can an endpoint under this host ever be
  PROVEN?" — which the egress seam has no notion of and deliberately does not
  want)
- the seam the admin agent routes refuse through (``src.admin.utils.url_policy``
  -> ``outbound_http.validate_url``): that one vector is refused, opaquely. The
  endpoint wiring itself is graded against a real database by
  ``tests/integration/test_admin_ingest_url_policy.py`` and
  ``tests/admin/test_agents.py``
  (``test_add_refuses_a_url_egress_policy_blocks_and_audits_the_refusal``,
  ``test_edit_*``): a test that mocks the session to watch the handler is a test
  of the mock (tests/CLAUDE.md § Which kind of test).
"""

import pytest


class TestReservedTldPolicy:
    """The half of the retired ``url_validator`` that SURVIVED #1802 still refuses.

    This is notification-proof policy, not address policy: it answers "can an
    endpoint under this hostname ever be PROVEN?", which the egress seam has no
    notion of — a ``.invalid`` host passes ``check_registration`` on its own
    terms. So this obligation has no home in the seam's parity table and keeps
    its owner here, where the module's own unit tests live.

    Deliberately narrow: ``tests/unit/test_architecture_reserved_tld_single_matcher.py``
    grades the *structural* rule (one matcher, boolean delegates to it, callers
    never re-match the frozenset). What is graded here is the policy VERDICT the
    F-04 file has always been about — which hosts get refused, which get through.
    """

    def test_dot_test_host_refused(self):
        from src.core.security.egress.policy import is_reserved_tld_host, reserved_tld_for_host

        assert reserved_tld_for_host("acme.test") == ".test"
        assert is_reserved_tld_host("acme.test") is True

    def test_dot_invalid_host_refused(self):
        from src.core.security.egress.policy import is_reserved_tld_host, reserved_tld_for_host

        assert reserved_tld_for_host("no-such-host.invalid") == ".invalid"
        assert is_reserved_tld_host("no-such-host.invalid") is True

    def test_normal_public_host_passes(self):
        """The non-vacuity half: a refusal that refuses everything grades nothing.

        ``signals.example.com`` is the trap spelling — ``.example`` IS reserved,
        but only as a TLD, and a call-site ``endswith(".example")`` that this
        owner exists to replace would get this one right while getting
        ``Acme.TEST`` and ``acme.test.`` wrong.
        """
        from src.core.security.egress.policy import is_reserved_tld_host, reserved_tld_for_host

        for host in ("signals.example.com", "creatives.example.com", "93.184.216.34"):
            assert reserved_tld_for_host(host) is None, host
            assert is_reserved_tld_host(host) is False, host


# A public, non-reserved address as a literal: the ingest gate's verdict on it is
# decided entirely by address policy, with no DNS lookup to go missing offline.
# (The mirror image of the reject case's host.docker.internal.)
SAFE_PUBLIC_URL = "https://93.184.216.34/agent"

# The vector the seam test pins: a docker-internal hostname on a private port,
# refused by address policy alone, so the verdict needs no DNS.
BLOCKED_INGEST_URL = "http://host.docker.internal:9999"


class TestSignalsAgentEndpointSSRFWiring:
    """The seam the agent routes' ingest refusal rests on.

    The routes' own tests grade the handler end to end against a real database
    (``tests/integration/test_admin_ingest_url_policy.py``,
    ``tests/admin/test_agents.py``). The three mock-session endpoint tests that
    used to live here are gone: they patched the handler's session factory and
    asserted on the mock, which grades the mock, not the handler
    (tests/CLAUDE.md § Which kind of test). What stays is the one fact those
    route tests assume and cannot grade themselves: that the seam refuses the
    vector, and refuses it opaquely.
    """

    def test_the_seam_raises_on_the_url_the_endpoints_reject(self):
        """A 302-back-to-the-form grades "something went wrong", not "egress policy said no".

        This pins the missing half: for a vector of the kind the route tests
        submit, the seam raises ``OutboundRequestBlocked`` — a raise, not a
        ``(bool, str)`` verdict, which is the contract change ``check_url_ssrf``
        -> ``validate_url`` made.

        The refusal is also asserted to be OPAQUE (AdCP 3.1.1,
        ``building/by-layer/L1/security.mdx`` point 6): the sentence handed back
        names neither the resolved address nor which rule fired, because the party
        that supplied the URL would otherwise have a host and port scanner. The
        general form of that rule is owned by
        ``tests/integration/test_outbound_http.py``; what is graded here is that THIS
        file's vector obeys it on the way to the operator.
        """
        from src.core.security.outbound_http import OutboundRequestBlocked, validate_url

        with pytest.raises(OutboundRequestBlocked) as blocked:
            validate_url(BLOCKED_INGEST_URL)

        message = str(blocked.value)
        for leak in ("host.docker.internal", "9999", "scheme", "https", "resolve failed"):
            assert leak not in message, f"refusal echoed {leak!r} back to the URL's supplier: {message!r}"

        # Non-vacuity: the same call admits the URL the accept-path test submits, so
        # the raise above is a verdict on the vector and not a blanket refusal.
        assert validate_url(SAFE_PUBLIC_URL) is None
