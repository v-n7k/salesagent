"""Decide whether the tests of a pull request redden on the base branch.

The red-on-base gate runs the tests that a pull request added or changed twice: on the head, and on
the head with the production roots reset to the base. A ``fix``, ``feat``, or ``security`` pull request
that changed a production root passes when at least one hosted changed test fails on the base and
passes on the head. This module turns the changed set, the pull request title, and the pytest JSON
reports of the two runs into that verdict and into the markdown table that the job writes to the step
summary.

Run it as ``python -m scripts.ci.redden_on_base``. The ``changed`` subcommand writes the changed set to a
JSON file, ``ids`` prints the node ids that one suite runs from that file, and ``verdict`` grades the
pytest reports of the two runs and appends the summary. Its exit code is 1 for a ``fail`` verdict and 0
otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.ci.changed_functions import DELETED, FunctionChange, changed_test_functions, touched_paths

# The roots that hold production code. The job resets them to the base between its two runs.
PRODUCTION_ROOTS: tuple[str, ...] = ("src", "templates", "static", "alembic")

# The conventional-commit types of a pull request that must come with a test that fails on the base.
GATED_PREFIXES: frozenset[str] = frozenset({"fix", "feat", "security"})

# The test directories that this job runs, each mapped to the suite whose pytest call runs it.
# A test in any other directory is listed as unhosted.
HOSTED_BUCKETS: dict[str, str] = {"tests/unit/": "unit", "tests/harness/": "unit", "tests/integration/": "integration"}

# The suites that run the hosted tests, each named once. The command line takes one report per suite.
_BUCKETS: tuple[str, ...] = tuple(dict.fromkeys(HOSTED_BUCKETS.values()))

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

    The document holds the pull request title that ``verdict`` graded, the verdict, a table with one row
    per changed test in the given order, and a list of the touched paths that hold no changed test
    function. A deleted test and a test in an unhosted suite show ``-`` for both outcomes.
    """
    lines = [
        "## Tests redden on base",
        "",
        f"Title: {title}",
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the subcommand that ``argv`` names and return its exit code."""
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except subprocess.CalledProcessError as err:
        # Git's own message is in ``err.stderr``, and the traceback does not show it.
        if isinstance(err.stderr, str):
            sys.stderr.write(err.stderr)
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.ci.redden_on_base",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    changed = commands.add_parser("changed", help="write the test functions that HEAD adds or changes to a JSON file")
    changed.add_argument("--repo", type=Path, default=Path("."), help="the git checkout to read (default: .)")
    changed.add_argument("--base", required=True, help="the base branch ref, such as HEAD^1 on a merge commit")
    changed.add_argument("--out", type=Path, required=True, help="the JSON file to write")
    changed.set_defaults(func=_changed)

    ids = commands.add_parser("ids", help="print the node ids that one suite runs, from the JSON that 'changed' wrote")
    ids.add_argument("changed", type=Path, metavar="FILE", help="the JSON that 'changed' wrote")
    ids.add_argument("bucket", choices=_BUCKETS, help="the suite whose ids to print")
    ids.set_defaults(func=_ids)

    graded = commands.add_parser("verdict", help="grade the two runs, append the summary, and exit 1 on a fail")
    graded.add_argument("--changed", type=Path, required=True, metavar="FILE", help="the JSON that 'changed' wrote")
    for side in ("head", "base"):
        graded.add_argument(
            f"--{side}-report",
            action=_ReportsByBucket,
            default={},
            metavar="BUCKET=PATH",
            help=f"the pytest-json-report file of the {side} run for one suite, repeated for each suite",
        )
    graded.add_argument("--title", required=True, help="the pull request title")
    graded.add_argument("--summary", type=Path, required=True, help="the markdown file to append the summary to")
    graded.set_defaults(func=_verdict)
    return parser


class _ReportsByBucket(argparse.Action):
    """Collect the repeated ``BUCKET=PATH`` values of one option into a dict from suite to report path."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        bucket, _, path = str(values).partition("=")
        if bucket not in _BUCKETS or not path:
            raise argparse.ArgumentError(
                self, f"expected BUCKET=PATH with BUCKET one of {', '.join(_BUCKETS)}, got '{values}'"
            )
        reports = getattr(namespace, self.dest)
        if bucket in reports:
            raise argparse.ArgumentError(self, f"the bucket '{bucket}' is named twice")
        setattr(namespace, self.dest, {**reports, bucket: Path(path)})


def _changed(args: argparse.Namespace) -> int:
    touched, changes = changed_test_functions(args.repo, args.base)
    document = {
        "base": args.base,
        "production_changed": production_changed(args.repo, args.base),
        "touched": touched,
        "changes": [{**asdict(change), "node_id": change.node_id} for change in changes],
    }
    args.out.write_text(json.dumps(document, indent=2) + "\n")
    return 0


def _ids(args: argparse.Namespace) -> int:
    changes = _changes(json.loads(args.changed.read_text()))
    print(" ".join(_hosted_ids(changes, args.bucket)))
    return 0


def _verdict(args: argparse.Namespace) -> int:
    document = json.loads(args.changed.read_text())
    changes = _changes(document)
    head = _side_outcomes(changes, args.head_report)
    base = _side_outcomes(changes, args.base_report)
    decision = verdict(
        title=args.title,
        production_changed=document["production_changed"],
        touched=document["touched"],
        changes=changes,
        head=head,
        base=base,
    )
    markdown = render_summary(
        title=args.title, verdict=decision, touched=document["touched"], changes=changes, head=head, base=base
    )
    with args.summary.open("a") as summary_file:
        summary_file.write(markdown)
    print(f"{decision.status}: {decision.reason}")
    return decision.exit_code


def _changes(document: Mapping[str, Any]) -> list[FunctionChange]:
    """Return the changes in a document that ``changed`` wrote."""
    return [FunctionChange(c["path"], c["qualname"], c["kind"]) for c in document["changes"]]


def _hosted_ids(changes: Iterable[FunctionChange], bucket: str) -> list[str]:
    """Return the node ids of the changed tests that the suite ``bucket`` runs, which leaves out the deleted ones."""
    return [change.node_id for change in changes if _is_hosted(change) and bucket_for(change.path) == bucket]


def _side_outcomes(changes: Sequence[FunctionChange], reports: Mapping[str, Path]) -> dict[str, str]:
    """Return the outcome of each hosted changed test on one side, read from the report of its suite.

    A suite that has no named report, or whose report file does not exist, reads ``ERROR`` for each of its tests.
    """
    merged: dict[str, str] = {}
    for bucket in _BUCKETS:
        path = reports.get(bucket)
        report = json.loads(path.read_text()) if path is not None and path.exists() else None
        merged |= outcomes(report, _hosted_ids(changes, bucket))
    return merged


if __name__ == "__main__":
    sys.exit(main())
