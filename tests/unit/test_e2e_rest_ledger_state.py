"""Lock test for the e2e_rest known-failures ledger (#1418, Wave 3).

The ledger (``tests/bdd/e2e_rest_known_failures.txt``) is a shrinking work-list of
e2e_rest BDD scenarios that fail over real HTTP. Wave 3 graduated every scenario
that now passes in-network and moved every format-injection-only scenario to an
env-level ``E2EUnsupportedSetup`` declaration (surfaced as xfail by the conftest
report hook, NOT listed in the ledger). What remains are genuine production /
harness gaps, enumerated below.

This test pins that end state so the ledger cannot silently drift:

* a removed entry that creeps back (a graduation regression) fails here;
* a genuine-gap entry deleted without landing the underlying fix fails here;
* the conftest loader must still read the same file the BDD suite xfails against.

When a gap is genuinely fixed (its scenario now passes in-network) or moved to an
env declaration, remove it from BOTH the ledger file and ``EXPECTED_LEDGER`` below
in the same change.
"""

from __future__ import annotations

from pathlib import Path

from tests.helpers.ledger import load_ledger_nodeids

# The 13 e2e_rest nodeids remaining: 7 genuine gaps + 2 parallel-e2e_rest
# mock-injection artifacts (owner-approved, added on the adcp-6.6 /
# perf/parallelize-test-suite work — see the block comment inside the set)
# + the adcp#7338 catalog row (2026-09-13) + 3 UC-010 targeting-shape rows
# (2026-09-15), both annotated at their entries below.
# 5 of that mock-injection block graduated 2026-09-15 (4 UC-004 delivery rows and
# the UC-005 format-id roundtrip row): the block's stated mechanism had gone stale,
# XPASS in-network innet_150926_0531, evidence at their former entries below.
# A SECOND #7338 row (@T-UC-005-main-referrals) was considered on 2026-09-15 and
# NOT added: it would have validated a document byte-identical to the row below
# while denying POST-S4 the only transport where the seller's real federation path
# runs. The redundant compliance Then was deleted from that scenario instead. The
# ledger file's #7338 block carries the reasoning and the measured scope.
# The 3 uc018 rows of that block graduated 2026-08-31: their Givens seed through
# the factories into the live server's own database, so the block's
# "injected cross-principal creatives" clause no longer describes them. XPASS in
# innet_270826_0338, innet_270826_1824 and innet_310826_1248; full evidence in
# the ledger file's block comment.
# Graduated on the way here: the 2 date-range boundary rows (2026-07-09, first
# in-network CI run), the 2 date-range partition twins (origin/pr-1417 merge,
# d4af23095 — strict-xfail XPASS in-network), and the 2 uc004 account valid rows
# (#1417 merge, jr5b seeded-account Given, XPASS innet_140726_1516).
# (47 after Wave 3 triage; jdy1
# graduated M3 6 get_products tenant-duplicate, M1 6 uc004 REST-422 wire-shape,
# M4 4 uc004 webhook-observability entries [now tag-declared in conftest]; the
# uc004 attribution campaign-interval boundary graduated at the main merge after
# upstream re-pointed its expected cell at error "VALIDATION_ERROR"; 12 uc006
# account billing-state entries graduated at the #1417 merge — its account
# resolution wiring makes them pass, xpass confirmed innet_040726_0013; 3 uc002
# creative extension entries imported at the #1417 merge — newly wired there,
# confirmed still failing in-network post-merge, innet_040726_0013; the uc004
# roas/cpa entry retired at #1430 item 4 — its Then steps now exist and the
# scenario is tag-declared T-UC-004-aggregated-roas-and-cpa on ALL transports;
# #1430 items 1-3 graduated the 6 uc011 read-back entries [_db_scope_for repoint
# + agent auth_token fix] and 2 uc002 ext-o/ext-p entries [auto-approval seeding],
# all 8 xpassed in-network, innet_050726_2030; the uc002 ext-q upload entry
# graduated after the fail_on_upload mock-fidelity + catalog-format +
# run_async_in_sync_context format-resolution fixes, verified in-network).
# Grouped by gap in the ledger file's section comments; flat here for exact-set
# comparison.
EXPECTED_LEDGER: frozenset[str] = frozenset(
    {
        # salesagent-3cs7o.54 — asset-level provenance absent from the stored
        # creative over e2e_rest only (passes on a2a/mcp/rest). The pin mandates
        # it and every source-readable hop is cleared by measurement; the next
        # step is a live-stack probe, so it is ledgered rather than guessed at.
        "tests/bdd/test_uc006_sync_creatives.py::test_inv5__assetlevel_provenance_replaces_creativelevel_entirely[e2e_rest]",
        # All four date-range invalid rows graduated: boundary rows 2026-07-09
        # (#1270 tripwires fired on the first in-network CI run — live server
        # validates start>=end now), partition twins at the origin/pr-1417 merge
        # (d4af23095, strict-xfail XPASS in-network).
        # Account valid rows graduated at the #1417 merge (jr5b seeded-account
        # Given; XPASS in-network innet_140726_1516) — see ledger note.
        "tests/bdd/test_uc004_deliver_media_buy_metrics.py::test_include_package_daily_breakdown_boundary__boundary_point[e2e_rest-string 'true' (non-boolean type)-\"true\"-invalid]",
        'tests/bdd/test_uc004_deliver_media_buy_metrics.py::test_reporting_dimensions_boundary__boundary_point[e2e_rest-geo with geo_level=metro but no system (behavioral gap)-{"geo": {"geo_level": "metro"}}-invalid]',
        "tests/bdd/test_uc004_deliver_media_buy_metrics.py::test_seller_ignores_attribution_request__returns_platform_default[e2e_rest]",
        "tests/bdd/test_uc011_manage_accounts.py::test_push_notification_for_async_status_changes__with_push_notification[e2e_rest]",
        # Added 2026-07-09 on the adcp-6.6 branch (owner-approved) when
        # perf/parallelize-test-suite enabled parallel e2e_rest (E2E_PER_WORKER):
        # mock-injection-incompatible artifacts, not regressions — UC-005
        # set_registry_formats is invisible to the separate HTTP server.
        #
        # The 4 UC-004 delivery rows and the UC-005 format-id roundtrip row graduated
        # 2026-09-15 (XPASS in-network, innet_150926_0531). The clause that routed the
        # UC-004 four named the wrong mechanism: #1418 gave set_adapter_response an e2e
        # realization that persists a DeliverySimulationConfig row the deployed server's
        # MockAdServer reads, so nothing is injected and nothing is invisible. The
        # roundtrip row was never a registry-injection case at all. Evidence per row is
        # in the ledger file's block comment.
        #
        # The third-party-agent row below stays: it xpasses VACUOUSLY (its one
        # discriminating assertion compares a raw agent_url against canonicalized
        # identities, so an id-only filter regression would still pass) and graduating
        # it would delete coverage rather than record it.
        "tests/bdd/test_uc005_discover_creative_formats.py::test_baseline_list_creative_formats_response_carries_format_id_objects_with_agent_url_and_id[e2e_rest]",
        "tests/bdd/test_uc005_discover_creative_formats.py::test_format_id_with_agent_url_pointing_at_a_thirdparty_creative_agent_is_reported_as_observation_not_failure[e2e_rest]",
        # Added 2026-09-13: @T-UC-005-main's Given moved from minted fmt_N ids to
        # reference-catalog formats, which retired its tag-level xfail on every
        # transport; over e2e_rest the live catalog carries pixel_tracker assets the
        # pinned Format.assets union does not admit (adcp#7338), so the compliance
        # Then fails there for the same reason as the three UC-005 rows above.
        # Upstream's own release is inconsistent with itself, which is why no change here
        # can graduate this row: the reference catalog captured at pin 467fd93d7711 -- the
        # same commit the feature files cite for the pinned schemas -- publishes
        # pixel_tracker on 45 of its 57 formats, and the adcp SDK from that release already
        # carries an UnknownFormatAsset fallback arm for exactly this ("AdCP enums grow
        # additively by design", strict on emit, lenient on parse). The JSON schema is the
        # half that did not get the arm. The one local "fix" -- stripping assets the pin
        # omits from the catalog this seller serves -- would tell a buyer a format needs
        # fewer assets than it does.
        "tests/bdd/test_uc005_discover_creative_formats.py::test_discover_full_format_catalog[e2e_rest]",
        # Added 2026-09-15: three UC-010 rows that configure a targeting SHAPE per
        # tenant (which metro systems, which country-keyed postal systems) and read
        # it back from get-adcp-capabilities-response.json
        # #/properties/media_buy/properties/execution/properties/targeting.
        # Production builds both blocks correctly -- the in-process rows prove it --
        # but there is no per-tenant surface to configure the shape over HTTP, and
        # adding one is refused twice over: TargetingCapabilities is adapter-CLASS
        # level by documented design (AdServerAdapter.get_targeting_capabilities is a
        # @staticmethod so discovery can read it without a Principal-bound instance,
        # INV-4 / salesagent-dn2s), and the declaration store carries no field for a
        # posture production cannot back ("the absence is the enforcement",
        # src/core/schemas/capability_declarations.py). The third option is the
        # test_behavior override read in src/core/ that a1b79d22d deleted and
        # prebid/salesagent#1891 questions. Their sibling channel and degradation rows
        # needed none of this: channels now come from Product.channels via
        # channel_helpers, and "adapter unavailable" is a real unresolvable
        # adapter_type. Full reasoning and the graduation condition are in the ledger
        # file's own block.
        "tests/bdd/test_uc010_discover_seller_capabilities.py::test_targeting_capability_configurations__partition[e2e_rest-nested_absent no nested sub-properties declared-no nested sub-properties true-geo_metros and geo_postal_areas absent from targeting]",
        'tests/bdd/test_uc010_discover_seller_capabilities.py::test_targeting_capability_configurations__partition[e2e_rest-nested_populated native postal map and metros-geo_metros.nielsen_dma=true, geo_postal_areas US=["zip"]-geo_metros equals {nielsen_dma: true} and geo_postal_areas has US containing "zip"]',
        'tests/bdd/test_uc010_discover_seller_capabilities.py::test_targeting_capability_configurations__partition[e2e_rest-postal_areas_native DE/CH/AT via native country-keyed map-geo_postal_areas DE=["plz"] CH=["plz"] AT=["plz"]-geo_postal_areas equals {DE: [plz], CH: [plz], AT: [plz]}]',
        # The 3 uc018 rows of this block GRADUATED 2026-08-31 on main (#1858): their
        # Givens seed through the factories into the live server's own database, so
        # the block's "injected cross-principal creatives" clause stopped describing
        # them. XPASS in innet_270826_0338, innet_270826_1824, innet_310826_1248.
        # Bug-triage epic salesagent-jl20 (2026-07-16) surfaced 2 genuine e2e-only
        # gaps by un-xfailing dn2s/mkso's scenarios; both graduated before landing
        # here, so neither is listed: uc010 auth-data-identity at salesagent-zna9
        # (_resolve_auth_dep now resolves tenant from headers regardless of
        # credential presence), and uc003 ext-a-unknown at salesagent-z9e0 (the harness
        # presents no token when no Principal row exists, so production's resolver
        # answers the failed lookup itself — all transports agree now).
    }
)

_LEDGER_PATH = Path(__file__).parent.parent / "bdd" / "e2e_rest_known_failures.txt"


def _load_ledger_nodeids() -> frozenset[str]:
    """Parse the ledger the way the conftest loader does (drop comments/blanks)."""
    return load_ledger_nodeids(_LEDGER_PATH)


def test_ledger_matches_expected_genuine_gaps() -> None:
    """The ledger file contains exactly the pinned genuine-gap nodeids."""
    actual = _load_ledger_nodeids()
    crept_back = actual - EXPECTED_LEDGER
    disappeared = EXPECTED_LEDGER - actual
    assert actual == EXPECTED_LEDGER, (
        "e2e_rest ledger drifted from its pinned Wave-3 end state.\n"
        f"Entries that crept back in (un-graduate them or update EXPECTED_LEDGER): {sorted(crept_back)}\n"
        f"Entries removed without updating this test: {sorted(disappeared)}"
    )


def test_ledger_entries_are_e2e_rest_bdd_nodeids() -> None:
    """Every ledger entry is a tests/bdd e2e_rest scenario nodeid."""
    for nodeid in _load_ledger_nodeids():
        assert nodeid.startswith("tests/bdd/"), f"non-bdd ledger entry: {nodeid}"
        assert "::" in nodeid, f"ledger entry is not a nodeid: {nodeid}"
        assert "e2e_rest" in nodeid, f"ledger entry is not an e2e_rest variant: {nodeid}"


def test_conftest_loader_reads_this_ledger() -> None:
    """The BDD conftest loads the same ledger this test pins.

    Guards against the loader being deleted or pointed elsewhere while the file
    still exists — that would silently stop xfailing these known failures.
    """
    from tests.bdd.conftest import _E2E_REST_KNOWN_FAILURES

    assert _E2E_REST_KNOWN_FAILURES == EXPECTED_LEDGER
