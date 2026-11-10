"""Decide whether the tests of a pull request redden on the base branch.

The red-on-base gate runs the tests that a pull request added or changed twice: on the head, and on
the head with the production roots reset to the base. A ``fix``, ``feat``, or ``security`` pull request
that changed a production root passes when at least one hosted changed test fails on the base and
passes on the head. This module turns the changed set, the pull request title, and the pytest JSON
reports of the two runs into that verdict and into the markdown table that the job writes to the step
summary.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.ci.changed_functions import DELETED, FunctionChange, touched_paths

# The roots that hold production code. The job resets them to the base between its two runs.
PRODUCTION_ROOTS: tuple[str, ...] = ("src", "templates", "static", "alembic")

# The conventional-commit types of a pull request that must come with a test that fails on the base.
GATED_PREFIXES: frozenset[str] = frozenset({"fix", "feat", "security"})

# The test directories that this job runs, each mapped to the suite whose pytest call runs it.
# A test in any other directory is listed as unhosted.
HOSTED_BUCKETS: dict[str, str] = {"tests/unit/": "unit", "tests/harness/": "unit", "tests/integration/": "integration"}

# The outcome strings are those of ``pytest-json-report``, plus ``NOT_COLLECTED``. ``SKIPPED`` stands
# for every row outcome that is neither a pass nor a failure: skipped, xfailed, and xpassed.
PASSED = "passed"
FAILED = "failed"
ERROR = "error"
SKIPPED = "skipped"
NOT_COLLECTED = "not collected"

# A test is red when it failed or errored, and green when it passed.
_RED = frozenset({FAILED, ERROR})


@dataclass(frozen=True)
class Verdict:
    """The decision of the gate, and the rule that made it.

    ``status`` is ``pass``, ``fail``, ``skip``, or ``advisory``. A ``skip`` marks a pull request whose
    changed tests this job cannot run, and ``advisory`` marks one that the gate does not grade.
    """

    status: str
    reason: str

    @property
    def exit_code(self) -> int:
        """Return the exit code of the job, which is 1 for ``fail`` and 0 for every other status."""
        return 1 if self.status == "fail" else 0


def title_prefix(title: str) -> str | None:
    """Return the conventional-commit type of ``title``, or ``None`` when the title has no such shape."""
    match = re.match(r"^([a-z]+)(\([^)]*\))?!?:", title)
    return match.group(1) if match else None


def bucket_for(path: str) -> str | None:
    """Return the suite that runs the tests under ``path``, or ``None`` when this job does not host them."""
    return next((bucket for prefix, bucket in HOSTED_BUCKETS.items() if path.startswith(prefix)), None)


def production_changed(repo_root: Path, base: str) -> bool:
    """Return whether ``HEAD`` adds, modifies, or deletes a file under a production root relative to ``base``."""
    return bool(touched_paths(repo_root, base, PRODUCTION_ROOTS))


def outcomes(report: Mapping[str, Any] | None, node_ids: Iterable[str]) -> dict[str, str]:
    """Return the outcome of each test in ``node_ids`` from a ``pytest-json-report`` document.

    A parametrized test has one row per parameter set, and its outcome covers all of them. It is
    ``FAILED`` when some row failed or errored, ``PASSED`` when every row passed, and ``SKIPPED`` for
    any other mix. A test with no row reads ``ERROR`` when a collector that failed covers it, which is
    how a module that cannot import on the base shows up, and ``NOT_COLLECTED`` otherwise. A ``None``
    report means that pytest wrote none, and every test reads ``ERROR``.
    """
    if report is None:
        return dict.fromkeys(node_ids, ERROR)
    by_test = _row_outcomes_by_test(report.get("tests", ()))
    failed_collectors = [c["nodeid"] for c in report.get("collectors", ()) if c["outcome"] == "failed"]
    return {node_id: _outcome(by_test.get(node_id, set()), node_id, failed_collectors) for node_id in node_ids}


def _row_outcomes_by_test(rows: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    by_test: dict[str, set[str]] = {}
    for row in rows:
        # The rows ``test_p[1]`` and ``test_p[2]`` belong to the test whose node id is ``test_p``.
        by_test.setdefault(row["nodeid"].partition("[")[0], set()).add(row["outcome"])
    return by_test


def _outcome(row_outcomes: set[str], node_id: str, failed_collectors: Sequence[str]) -> str:
    """Return the outcome of one test from the outcomes of its rows, or from the failed collectors when it has none."""
    if row_outcomes & _RED:
        return FAILED
    if row_outcomes:
        return PASSED if row_outcomes == {PASSED} else SKIPPED
    if any(_covers(collector, node_id) for collector in failed_collectors):
        return ERROR
    return NOT_COLLECTED


def _covers(collector: str, node_id: str) -> bool:
    """Return whether the failed collector ``collector`` covers ``node_id``.

    A collector covers its own node id and the node ids beneath it, where a module or a class holds
    ``::`` and a directory holds ``/``. The root collector has the empty node id and covers all of
    them. Matching by segment keeps the collector of ``tests/unit/sub`` from covering
    ``tests/unit/subsequent/test_b.py::test_x``, and the collector of ``TestK`` from covering ``TestKx``.
    """
    return not collector or node_id == collector or node_id.startswith((f"{collector}::", f"{collector}/"))


def verdict(
    *,
    title: str,
    production_changed: bool,
    touched: Sequence[str],
    changes: Sequence[FunctionChange],
    head: Mapping[str, str],
    base: Mapping[str, str],
) -> Verdict:
    """Return the verdict for a pull request, from the first rule that decides.

    1. A title whose type is not gated, or a pull request that changed no production root, is ``advisory``.
    2. A pull request that touched no file under ``tests/`` is a ``fail``.
    3. A pull request whose changed tests are all deleted or in an unhosted suite is a ``skip``.
    4. A pull request with a hosted changed test that is red on the base and green on the head is a ``pass``.
    5. Any other pull request is a ``fail``. That includes one whose changes under ``tests/`` hold no test
       function, such as a change to a conftest.

    ``head`` and ``base`` map a node id to its outcome, and a node id that one of them lacks reads ``ERROR``.
    """
    prefix = title_prefix(title)
    if prefix not in GATED_PREFIXES:
        return Verdict("advisory", f"title type '{prefix or 'none'}' is not gated")
    if not production_changed:
        return Verdict("advisory", "no production root changed")
    if not touched:
        return Verdict("fail", "the PR touches no file under tests/")
    hosted = [change for change in changes if _is_hosted(change)]
    if changes and not hosted:
        return Verdict("skip", "every changed test is in a suite this job does not host")
    reddened = next((change for change in hosted if _reddens(change, head, base)), None)
    if reddened is not None:
        return Verdict("pass", f"{reddened.node_id} is red on base and green on head")
    return Verdict("fail", "no hosted changed test is red on base and green on head")


def _is_hosted(change: FunctionChange) -> bool:
    """Return whether this job runs ``change``, which excludes a deleted test and a test in an unhosted suite."""
    return change.kind != DELETED and bucket_for(change.path) is not None


def _base_and_head(change: FunctionChange, head: Mapping[str, str], base: Mapping[str, str]) -> tuple[str, str]:
    """Return the outcome of ``change`` on the base and on the head, where a side without one reads ``ERROR``."""
    return base.get(change.node_id, ERROR), head.get(change.node_id, ERROR)


def _reddens(change: FunctionChange, head: Mapping[str, str], base: Mapping[str, str]) -> bool:
    on_base, on_head = _base_and_head(change, head, base)
    return on_base in _RED and on_head == PASSED


def render_summary(
    *,
    title: str,
    verdict: Verdict,
    touched: Sequence[str],
    changes: Sequence[FunctionChange],
    head: Mapping[str, str],
    base: Mapping[str, str],
) -> str:
    """Return the markdown that the job writes to the step summary, whatever the verdict is.

    The document holds the verdict, a table with one row per changed test in the given order, and a list
    of the touched paths that hold no changed test function. A deleted test and a test in an unhosted
    suite show ``-`` for both outcomes. ``title`` is the pull request title that ``verdict`` graded, and
    the layout does not print it.
    """
    lines = [
        "## Tests redden on base",
        "",
        f"**{verdict.status}**: {verdict.reason}",
        "",
        "| test | kind | suite | on base | on head |",
        "| --- | --- | --- | --- | --- |",
        *(_table_row(change, head, base) for change in changes),
    ]
    paths_with_changes = {change.path for change in changes}
    untested = [path for path in touched if path not in paths_with_changes]
    if untested:
        lines += ["", "Touched without a changed test function:", *(f"- {path}" for path in untested)]
    return "\n".join(lines) + "\n"


def _table_row(change: FunctionChange, head: Mapping[str, str], base: Mapping[str, str]) -> str:
    on_base, on_head = _base_and_head(change, head, base) if _is_hosted(change) else ("-", "-")
    return f"| {change.node_id} | {change.kind} | {bucket_for(change.path) or 'unhosted'} | {on_base} | {on_head} |"
