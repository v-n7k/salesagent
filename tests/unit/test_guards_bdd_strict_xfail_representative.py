"""Guard: the BDD strict-xfail xpass tripwire must not go dead for scenarios
outside the T-UC-010 opt-in.

``pytest_collection_modifyitems`` (tests/bdd/conftest.py) deselects the
mcp/rest variants of any strict-xfail scenario by default (BDD_ALL_TRANSPORTS
unset), keeping only the a2a variant as the "representative". For a scenario
whose strict-xfail marker is applied ONLY to mcp/rest (a2a already validates
and carries no marker -- the real pattern for T-UC-004-daterange-invalid,
T-UC-004-partition-reporting-dims, etc., confirmed 2026-07-25: running the
whole UC-004 file with BDD_ALL_TRANSPORTS=1 surfaces 13 genuine
XPASS(strict) failures, ALL on mcp/rest, NONE on a2a), the default run
deselects the only items that carry the tripwire and keeps the one item
(a2a) that never had it. The scenario silently stops proving its production
gap: no item in the default collection can ever XPASS(strict), so a
production fix in that gap goes undetected forever.

Drives the REAL pytest_collection_modifyitems via minimal stand-in Items
(same technique as test_bdd_e2e_enabled_xdist_guard.py's stub config).
"""

from __future__ import annotations

import pytest

from tests.bdd.conftest import pytest_collection_modifyitems


class _FakeConfig:
    def __init__(self):
        self.deselected: list[_FakeItem] = []
        self.hook = self

    def pytest_deselected(self, items):
        self.deselected.extend(items)


class _FakeItem:
    def __init__(self, nodeid, marks=()):
        self.nodeid = nodeid
        self.own_markers = list(marks)
        self.config = None  # set once all items exist, see _make_items()

    def iter_markers(self, name=None):
        for m in self.own_markers:
            if name is None or m.name == name:
                yield m

    def add_marker(self, marker):
        mark = marker.mark if hasattr(marker, "mark") else marker
        self.own_markers.append(mark)


def _make_items(tag: str, transports: tuple[str, ...] = ("a2a", "mcp", "rest")):
    """One scenario, one item per transport -- strict xfail on mcp/rest only.

    Mirrors the real-world shape found in tests/bdd/conftest.py (e.g. the
    T-UC-004-boundary-date-range ``_dr_invalid_fail`` predicate explicitly
    excludes a2a because "a2a now validates ... mcp/rest still don't").

    *transports* is what ``pytest_generate_tests`` parametrized, so a
    ``no_rest_uc`` scenario -- a UC whose tool has no REST route, legitimately
    and stably graded on a2a + mcp -- is ``("a2a", "mcp")``.
    """
    tag_mark = pytest.Mark(tag, (), {})
    strict_xfail = pytest.mark.xfail(reason="mcp/rest validation gap", strict=True).mark
    items = [
        _FakeItem(
            f"tests/bdd/test_fake.py::test_thing[{transport}-row]",
            marks=[tag_mark] if transport == "a2a" else [tag_mark, strict_xfail],
        )
        for transport in transports
    ]
    config = _FakeConfig()
    for item in items:
        item.config = config
    return items, config


def test_default_run_deselects_the_only_items_carrying_the_strict_xfail_tripwire(monkeypatch):
    """Non-UC-010 scenario: default collection must not strip every strict-xfail
    item, or a production fix in that gap can never surface as an XPASS."""
    monkeypatch.delenv("BDD_ALL_TRANSPORTS", raising=False)
    items, config = _make_items("T-UC-999-fake")

    pytest_collection_modifyitems(items)

    remaining_nodeids = {i.nodeid for i in items}
    remaining_strict_xfail = [
        i for i in items if any(m.name == "xfail" and m.kwargs.get("strict") for m in i.iter_markers())
    ]

    assert remaining_strict_xfail, (
        "the single-transport optimization deselected every item carrying the strict-xfail "
        f"tripwire for a non-T-UC-010 scenario; remaining items: {sorted(remaining_nodeids)} -- "
        "a production fix in this gap can never XPASS and surface in CI"
    )


def test_bdd_all_transports_preserves_the_tripwire(monkeypatch):
    """Sanity check: the opt-out env var restores full coverage (control case)."""
    monkeypatch.setenv("BDD_ALL_TRANSPORTS", "1")
    items, config = _make_items("T-UC-999-fake")

    pytest_collection_modifyitems(items)

    remaining_strict_xfail = [
        i for i in items if any(m.name == "xfail" and m.kwargs.get("strict") for m in i.iter_markers())
    ]
    assert len(remaining_strict_xfail) == 2  # mcp + rest, untouched


# ---------------------------------------------------------------------------
# The representative must not be PICKED. Order-independence.
# ---------------------------------------------------------------------------
#
# The hook used to keep the FIRST mcp/rest sibling it walked per scenario
# (``kept_representatives``) and deselect the other. ``items`` order is
# shuffled by pytest-randomly, which the bdd_inprocess env runs with a fresh
# seed every run (tox.ini passes -p no:randomly to `integration`, not to
# `bdd_inprocess`), so WHICH of mcp/rest survived changed run to run with no
# code change. Measured on tests/bdd/test_uc010_discover_seller_capabilities.py:
# a2a 196 every seed, but mcp/rest split 183/166, 171/178, 174/175 for seeds
# 1/2/3 -- the same 349 slots, redistributed.
#
# That is a transport dropped at collection, which tests/bdd/conftest.py's own
# note calls "exactly as ungraded as an xfail but invisible to both escape-hatch
# detectors" -- and nondeterministically, so a defect on the skipped transport
# appears and disappears between runs. It also defeats every "zero regressions"
# claim made by diffing nodeid sets: ~19 removed / ~19 added reads as the benign
# transport-parameter noise scripts/audit/compare_runs.py documents.
#
# The fix is not a stable pick. A pick is an omission under another name, and a
# fence around it reads as permission: the rule is all-or-none per scenario, so
# there is no sibling left to choose between. These two tests pin the PROPERTY
# (collection does not depend on order), not today's counts.


def _survivors(items) -> set[str]:
    pytest_collection_modifyitems(items)
    return {i.nodeid for i in items}


def test_collection_does_not_depend_on_item_order(monkeypatch):
    """Same items, reversed order, same survivors.

    Reversal is the minimal permutation that exposes a first-wins pick: with
    ``kept_representatives`` the mcp sibling survived one order and the rest
    sibling the other.
    """
    monkeypatch.delenv("BDD_ALL_TRANSPORTS", raising=False)

    forward, _ = _make_items("T-UC-010-fake")
    backward, _ = _make_items("T-UC-010-fake")
    backward.reverse()

    assert _survivors(forward) == _survivors(backward), (
        "the strict-xfail representative depends on collection order, so which transport "
        "grades this scenario changes with pytest-randomly's per-run seed"
    )


def test_an_opted_in_scenario_keeps_every_transport_not_one_of_them(monkeypatch):
    """All-or-none, so there is no sibling to pick between.

    T-UC-010 opts in to keeping a wire representative beyond a2a. Keeping ONE
    arbitrary sibling is what made the choice order-dependent; keeping both
    makes the omission unrepresentable rather than merely stable.
    """
    monkeypatch.delenv("BDD_ALL_TRANSPORTS", raising=False)
    items, _ = _make_items("T-UC-010-fake")

    survivors = _survivors(items)

    assert survivors == {
        "tests/bdd/test_fake.py::test_thing[a2a-row]",
        "tests/bdd/test_fake.py::test_thing[mcp-row]",
        "tests/bdd/test_fake.py::test_thing[rest-row]",
    }, f"an opted-in scenario kept a subset of its transports: {sorted(survivors)}"


def test_a_declared_two_transport_scenario_keeps_both_of_them(monkeypatch):
    """The legitimate two-transport case survives all-or-none unchanged.

    A ``no_rest_uc`` scenario (a UC whose tool has no REST route) is
    parametrized [a2a, mcp] by ``pytest_generate_tests`` -- declared at
    parametrization and stable, which is the opposite of the emergent rotation
    all-or-none removes. The deselection hook must not turn it into a2a alone:
    with one redundant-transport item there was never a choice to make, and
    there must still be none.
    """
    monkeypatch.delenv("BDD_ALL_TRANSPORTS", raising=False)
    items, _ = _make_items("T-UC-010-fake", transports=("a2a", "mcp"))

    survivors = _survivors(items)

    assert survivors == {
        "tests/bdd/test_fake.py::test_thing[a2a-row]",
        "tests/bdd/test_fake.py::test_thing[mcp-row]",
    }, f"a declared two-transport scenario lost a transport at collection: {sorted(survivors)}"
