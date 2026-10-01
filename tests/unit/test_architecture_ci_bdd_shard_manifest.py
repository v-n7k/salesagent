"""Guard: BDD CI shards cover every tests/bdd file exactly once."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from scripts.ci.shard_split import (
    SHARD_COUNTS,
    _assign_greedy_by_cost,
    assign_files_to_shards,
    bdd_scenario_count,
    file_cost,
    list_suite_files,
)
from scripts.ci.workflow_helpers import CI_WORKFLOW_PATH

_REPO_ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def _restored_environ() -> Iterator[None]:
    """Undo any environment change the nested session makes.

    ``tests/harness/_base.py`` and ``tests/conftest.py`` set their knobs with
    ``setdefault`` at import, so collecting tests/bdd in-process can introduce a
    key this worker did not have. None of them is harmful today, but a unit worker
    that silently acquires a flag from an unrelated suite is the kind of leak that
    is only ever diagnosed the hard way.
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


class _BddModuleRecorder:
    """Records every module the inner collection produces, as data rather than text."""

    def __init__(self) -> None:
        self.paths: set[str] = set()

    def pytest_collectstart(self, collector: pytest.Collector) -> None:
        if isinstance(collector, pytest.Module):
            self.paths.add(Path(collector.path).relative_to(_REPO_ROOT).as_posix())


def _pytest_bdd_module_paths(repo_root: Path) -> set[str]:
    """Collect BDD test module paths via pytest (independent of shard_split glob).

    pytest is the SECOND oracle here, and that is the whole point of this guard:
    ``assigned`` below comes from ``shard_split``'s glob, ``expected`` comes from
    what pytest itself decides to collect, and only their disagreement can reveal
    a BDD module that runs in no shard. Deriving both sides from the same globbing
    logic would compare the glob to a reimplementation of itself and pass forever.

    The collection runs IN-PROCESS. It used to be a subprocess with
    ``timeout=120``, which made this structural guard assert on wall clock: the
    work is ~6s, but under the full gate's own parallelism the child is starved
    rather than slow, and the 120s budget expired. It then failed as "the shards
    do not partition the suite" when nothing about the shards was wrong. In-process
    there is no budget to exceed — the call simply takes as long as it takes.

    Importing ``tests/bdd`` here is safe, and that was measured rather than assumed:
    the collection opens no socket at all — no database, no network — and the only
    environment key it sets that a unit worker would not already have is
    ``ADCP_RUN_BACKGROUND_SCHEDULERS`` (``tests/harness/_base.py``, via
    ``setdefault``). :func:`_restored_environ` puts even that back, so the helper is
    environment-neutral by construction rather than by luck, and
    ``test_restored_environ_undoes_what_the_nested_session_does`` holds it there.

    What it does cost is memory: the nested import adds ~2500 modules and ~490 MB
    of RSS to whichever unit worker runs this test, and that stays resident for the
    rest of the session where the old subprocess's copy died with the child. One
    worker out of sixteen, and it buys the removal of a wall-clock assertion.
    """
    recorder = _BddModuleRecorder()
    with _restored_environ():
        exit_code = pytest.main(
            [
                str(repo_root / "tests" / "bdd"),
                "--collect-only",
                # The inner session must not write the outer session's cache, or it
                # would clobber the outer ``--lf`` state with tests/bdd's results.
                # ``-p no:terminal`` is NOT available to silence its collection tree:
                # this repo's ``addopts`` carries ``-v --tb=short``, which the terminal
                # plugin is what registers, so disabling it makes them unparseable.
                # The tree goes to the outer session's capture instead.
                "-p",
                "no:cacheprovider",
            ],
            plugins=[recorder],
        )
    if exit_code != pytest.ExitCode.OK:
        pytest.fail(f"in-process --collect-only of tests/bdd/ failed with exit code {exit_code!r}")

    if not recorder.paths:
        pytest.fail("in-process --collect-only of tests/bdd/ produced no BDD module paths")
    return recorder.paths


@pytest.mark.arch_guard
def test_bdd_shards_partition_suite() -> None:
    expected = _pytest_bdd_module_paths(_REPO_ROOT)
    buckets = assign_files_to_shards("bdd", repo_root=_REPO_ROOT)
    assigned = {path for paths in buckets.values() for path in paths}

    assert len(buckets) == SHARD_COUNTS["bdd"]
    assert assigned == expected


@pytest.mark.arch_guard
def test_restored_environ_undoes_what_the_nested_session_does() -> None:
    """Pin the mechanism that keeps the in-process oracle from leaking env state.

    Collecting tests/bdd in this process imports that suite's conftest and step
    plugins, which set their knobs with ``setdefault`` at import. Measured, the one
    key a unit worker does not already carry is ADCP_RUN_BACKGROUND_SCHEDULERS;
    :func:`_restored_environ` is what puts it back.

    This asserts on the context manager rather than on a before/after around
    :func:`_pytest_bdd_module_paths`, and the reason is worth stating so nobody
    "improves" it back: the leak is a FIRST-IMPORT effect. ``setdefault`` writes
    only when the key is absent, and the module holding it is only imported once
    per process, so any second collection is env-neutral no matter what this
    function does. An integration-level before/after therefore passes with the
    restoration deleted whenever another test in this module collected first --
    verified, it did exactly that. It could only fail when it happened to run
    first, which under ``--dist loadfile`` it never does. That assertion cannot
    fail where it matters; this one can, and does when the body below is gutted.
    """
    added_key = "PRKV60_ADDED"
    changed_key = "PRKV60_CHANGED"
    removed_key = "PRKV60_REMOVED"
    os.environ[changed_key] = "original"
    os.environ[removed_key] = "present"
    try:
        before = dict(os.environ)

        with _restored_environ():
            os.environ[added_key] = "leaked"
            os.environ[changed_key] = "overwritten"
            del os.environ[removed_key]

        assert dict(os.environ) == before, (
            "the nested session's environment changes outlived it: "
            f"added={ {k: v for k, v in os.environ.items() if k not in before} } "
            f"removed={[k for k in before if k not in os.environ]}"
        )
    finally:
        for key in (added_key, changed_key, removed_key):
            os.environ.pop(key, None)


@pytest.mark.arch_guard
def test_ci_bdd_matrix_matches_shard_config() -> None:
    workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["bdd-tests-shard"]["strategy"]["matrix"]["shard"]
    assert matrix == list(range(1, SHARD_COUNTS["bdd"] + 1))


@pytest.mark.arch_guard
def test_ci_bdd_shard_job_name_uses_matrix_total() -> None:
    """Shard denominator must follow matrix size (not a hardcoded literal)."""
    workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    name = workflow["jobs"]["bdd-tests-shard"]["name"]
    assert "strategy.job-total" in name, (
        "bdd-tests-shard job name must use strategy.job-total for the shard denominator."
    )


@pytest.mark.arch_guard
def test_bdd_shards_have_discoverable_scenario_counts() -> None:
    for path in list_suite_files("bdd", repo_root=_REPO_ROOT):
        assert bdd_scenario_count(path, repo_root=_REPO_ROOT) >= 1


@pytest.mark.arch_guard
def test_bdd_greedy_split_rejects_shard_count_above_file_count() -> None:
    files = list_suite_files("bdd", repo_root=_REPO_ROOT)
    with pytest.raises(ValueError, match="shard would be empty"):
        _assign_greedy_by_cost(files, len(files) + 1, _REPO_ROOT)


@pytest.mark.arch_guard
def test_bdd_shard_measured_load_is_balanced() -> None:
    """Shard totals stay within 20% of each other, measured in SECONDS.

    Graded on ``file_cost`` -- the recorded duration -- and not on scenario count,
    because scenario count is what let the split go unbalanced while this guard
    stayed green. On run innet_150926_0531 the counts were 586 against 569, a 1.03
    ratio this tolerance passes comfortably, while the shards actually held 120 and
    91 minutes and CI killed both at its 25-minute cap.

    The band is tighter than the 1.35 it replaces because the signal is now the
    thing that matters: with longest-first packing over measured costs there is no
    reason for a 20% spread, and a wider band would re-admit the skew.
    """
    buckets = assign_files_to_shards("bdd", repo_root=_REPO_ROOT)
    loads = [sum(file_cost(path, repo_root=_REPO_ROOT) for path in paths) for paths in buckets.values()]
    assert loads, "BDD shard assignment produced no files"
    assert min(loads) > 0, f"a shard carries no measurable work: {loads}"
    assert max(loads) / min(loads) <= 1.20, (
        "BDD shard measured loads too skewed "
        f"(minutes): { ({k: round(v / 60, 1) for k, v in zip(buckets.keys(), loads, strict=True)}) }. "
        "Refresh scripts/ci/bdd_shard_timings.json from a recent run."
    )


@pytest.mark.arch_guard
def test_new_bdd_file_is_priced_not_treated_as_free() -> None:
    """A file absent from the timing map costs its scenarios at the suite rate.

    The failure this prevents: an unpriced file reads as zero cost, so every new
    file lands on whichever shard therefore looks emptiest, and the newest tests --
    the ones most likely to be slow -- pile onto one runner.
    """
    unknown = "tests/bdd/test_not_in_the_timing_map.py"
    from scripts.ci.shard_split import _recorded_timings

    assert unknown not in _recorded_timings()
    known = next(iter(_recorded_timings()))
    assert file_cost(known, repo_root=_REPO_ROOT) > 0
