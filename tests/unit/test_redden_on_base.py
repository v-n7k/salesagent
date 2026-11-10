"""Tests for the red-on-base gate: the outcome of each test, the rules in order, the summary, and the command line."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

import pytest

from scripts.ci.changed_functions import ADDED, CHANGED, DELETED, FunctionChange
from scripts.ci.redden_on_base import (
    ERROR,
    FAILED,
    NOT_COLLECTED,
    PASSED,
    SKIPPED,
    Verdict,
    bucket_for,
    incomplete_runs,
    main,
    outcomes,
    render_summary,
    title_prefix,
    verdict,
)
from tests.helpers.scratch_repo import git, git_repo, write
from tests.unit._architecture_helpers import repo_root


def test_title_prefix_reads_the_conventional_type() -> None:
    assert title_prefix("fix(admin): bind the callback") == "fix"
    assert title_prefix("feat!: drop a field") == "feat"
    assert title_prefix("Update README") is None


def test_bucket_for_hosts_unit_harness_and_integration_only() -> None:
    assert bucket_for("tests/unit/test_x.py") == "unit"
    assert bucket_for("tests/harness/test_x.py") == "unit"
    assert bucket_for("tests/integration/test_x.py") == "integration"
    assert bucket_for("tests/bdd/test_x.py") is None


def test_outcomes_parametrized_rows_and_collection_errors() -> None:
    report = {
        "tests": [
            {"nodeid": "tests/unit/test_a.py::test_p[1]", "outcome": "passed"},
            {"nodeid": "tests/unit/test_a.py::test_p[2]", "outcome": "failed"},
            {"nodeid": "tests/unit/test_a.py::TestK::test_m", "outcome": "passed"},
        ],
        "collectors": [{"nodeid": "tests/unit/test_new.py", "outcome": "failed"}],
    }
    ids = [
        "tests/unit/test_a.py::test_p",
        "tests/unit/test_a.py::TestK::test_m",
        "tests/unit/test_new.py::test_n",
        "tests/unit/test_a.py::test_absent",
    ]
    assert outcomes(report, ids) == {ids[0]: FAILED, ids[1]: PASSED, ids[2]: ERROR, ids[3]: NOT_COLLECTED}


def _collector_report(nodeid: str, outcome: str = "failed") -> dict[str, list[dict[str, str]]]:
    return {"tests": [], "collectors": [{"nodeid": nodeid, "outcome": outcome}]}


def test_outcomes_match_a_failed_collector_by_path_segment() -> None:
    ids = [
        "tests/unit/sub/test_a.py::TestK::test_m",
        "tests/unit/sub/test_a.py::TestKx::test_m",
        "tests/unit/subsequent/test_b.py::test_x",
    ]
    # A plain prefix match would let the collector of ``sub`` claim ``subsequent``, and ``TestK`` claim ``TestKx``.
    by_directory = outcomes(_collector_report("tests/unit/sub"), ids)
    assert by_directory == {ids[0]: ERROR, ids[1]: ERROR, ids[2]: NOT_COLLECTED}
    by_class = outcomes(_collector_report("tests/unit/sub/test_a.py::TestK"), ids)
    assert by_class == {ids[0]: ERROR, ids[1]: NOT_COLLECTED, ids[2]: NOT_COLLECTED}
    assert set(outcomes(_collector_report(""), ids).values()) == {ERROR}  # The root collector covers every test.
    assert outcomes(_collector_report(ids[0]), ids[:1]) == {ids[0]: ERROR}  # A collector covers its own node id.
    assert set(outcomes(_collector_report("", "skipped"), ids).values()) == {NOT_COLLECTED}  # Only a failed one counts.


def test_outcomes_fold_error_rows_into_failed_and_skipped_rows_into_skipped() -> None:
    report = {
        "tests": [
            {"nodeid": "tests/unit/test_a.py::test_e", "outcome": "error"},
            {"nodeid": "tests/unit/test_a.py::test_s", "outcome": "skipped"},
            {"nodeid": "tests/unit/test_a.py::test_m[1]", "outcome": "passed"},
            {"nodeid": "tests/unit/test_a.py::test_m[2]", "outcome": "xfailed"},
        ],
        "collectors": [],
    }
    ids = ["tests/unit/test_a.py::test_e", "tests/unit/test_a.py::test_s", "tests/unit/test_a.py::test_m"]
    assert outcomes(report, ids) == {ids[0]: FAILED, ids[1]: SKIPPED, ids[2]: SKIPPED}


def test_outcomes_without_a_report_are_errors() -> None:
    assert outcomes(None, ["tests/unit/test_a.py::test_x"]) == {"tests/unit/test_a.py::test_x": ERROR}


CHANGE = FunctionChange("tests/unit/test_a.py", "test_x", CHANGED)
ID = CHANGE.node_id


def test_verdict_advisory_for_an_ungated_title_or_no_production_change() -> None:
    assert (
        verdict(
            title="refactor: x",
            production_changed=True,
            touched=["tests/unit/test_a.py"],
            changes=[CHANGE],
            head={ID: PASSED},
            base={ID: PASSED},
        ).status
        == "advisory"
    )
    assert (
        verdict(
            title="fix: x",
            production_changed=False,
            touched=["tests/unit/test_a.py"],
            changes=[CHANGE],
            head={ID: PASSED},
            base={ID: PASSED},
        ).status
        == "advisory"
    )


def test_verdict_fails_when_no_test_file_was_touched() -> None:
    v = verdict(title="fix: x", production_changed=True, touched=[], changes=[], head={}, base={})
    assert (v.status, v.exit_code) == ("fail", 1)


def test_verdict_skips_when_every_changed_test_is_unhosted_or_deleted() -> None:
    bdd = FunctionChange("tests/bdd/test_uc.py", "test_s", ADDED)
    gone = FunctionChange("tests/unit/test_a.py", "test_old", DELETED)
    v = verdict(
        title="fix: x",
        production_changed=True,
        touched=[bdd.path, gone.path],
        changes=[bdd, gone],
        head={},
        base={},
    )
    assert (v.status, v.exit_code) == ("skip", 0)


def _grade(
    changes: Sequence[FunctionChange],
    head: Mapping[str, str],
    base: Mapping[str, str],
    *,
    title: str = "fix: x",
    incomplete: Sequence[str] = (),
) -> Verdict:
    """Return the verdict for a pull request that changed production and touched the files of ``changes``."""
    return verdict(
        title=title,
        production_changed=True,
        touched=sorted({change.path for change in changes}),
        changes=changes,
        head=head,
        base=base,
        incomplete=incomplete,
    )


def test_verdict_treats_a_test_the_head_did_not_collect_as_unhosted() -> None:
    # The job runs the integration suite with a marker expression that deselects the creative group.
    creative = FunctionChange("tests/integration/test_creative.py", "test_c", CHANGED)
    uncollected = {creative.node_id: NOT_COLLECTED}
    skipped = _grade([creative], head=uncollected, base=uncollected)
    reason = "every changed test is deleted, in a suite this job does not host, or not collected on the head"
    assert skipped == Verdict("skip", reason)
    # A changed test that the head run did collect still decides.
    head, base = {**uncollected, ID: PASSED}, {**uncollected, ID: FAILED}
    assert _grade([creative, CHANGE], head=head, base=base) == Verdict("pass", f"{ID} is red on base and green on head")


def test_verdict_errors_when_a_needed_run_did_not_complete() -> None:
    head, base = {ID: PASSED}, {ID: FAILED}
    assert _grade([CHANGE], head, base).status == "pass"  # Only the missing run turns these outcomes into an error.
    error = _grade([CHANGE], head, base, incomplete=["base unit: no report"])
    assert error == Verdict("error", "a run did not complete: base unit: no report")
    assert error.exit_code == 1
    # The rule comes before the title rule, so a title that the gate does not grade still shows a broken job.
    assert _grade([CHANGE], head, base, title="refactor: x", incomplete=["base unit: no report"]) == error
    both = _grade([CHANGE], head, base, incomplete=["head unit: pytest exit 4", "base unit: no report"])
    assert both.reason == "a run did not complete: head unit: pytest exit 4; base unit: no report"


def test_verdict_passes_only_on_red_base_and_green_head() -> None:
    assert (
        verdict(
            title="fix: x",
            production_changed=True,
            touched=[CHANGE.path],
            changes=[CHANGE],
            head={ID: PASSED},
            base={ID: FAILED},
        ).status
        == "pass"
    )
    assert (
        verdict(
            title="fix: x",
            production_changed=True,
            touched=[CHANGE.path],
            changes=[CHANGE],
            head={ID: PASSED},
            base={ID: ERROR},
        ).status
        == "pass"
    )
    assert (
        verdict(
            title="fix: x",
            production_changed=True,
            touched=[CHANGE.path],
            changes=[CHANGE],
            head={ID: PASSED},
            base={ID: PASSED},
        ).status
        == "fail"
    )
    assert (
        verdict(
            title="fix: x",
            production_changed=True,
            touched=[CHANGE.path],
            changes=[CHANGE],
            head={ID: FAILED},
            base={ID: FAILED},
        ).status
        == "fail"
    )


def _status(on_base: str | None, on_head: str | None) -> str:
    """Return the verdict for the one hosted changed test, where ``None`` leaves that side out of the outcomes."""
    return verdict(
        title="fix: x",
        production_changed=True,
        touched=[CHANGE.path],
        changes=[CHANGE],
        head={} if on_head is None else {ID: on_head},
        base={} if on_base is None else {ID: on_base},
    ).status


def test_verdict_counts_only_failed_or_error_as_red_and_only_passed_as_green() -> None:
    assert [_status(on_base, PASSED) for on_base in (SKIPPED, NOT_COLLECTED, PASSED)] == ["fail"] * 3
    # A head run that wrote no report reads ERROR for every test, and that is never green.
    assert [_status(FAILED, on_head) for on_head in (SKIPPED, ERROR, None)] == ["fail"] * 3
    assert _status(FAILED, NOT_COLLECTED) == "skip"  # The head run did not collect it, so nothing grades it.
    assert _status(None, PASSED) == "pass"  # A test that the base run did not report reads ERROR there.


def test_verdict_grades_only_the_gated_title_types() -> None:
    types = ("fix", "feat", "security", "refactor", "perf", "chore", "docs", "test", "ci")
    graded = [
        t
        for t in types
        if verdict(title=f"{t}: x", production_changed=True, touched=[], changes=[], head={}, base={}).status
        != "advisory"
    ]
    assert graded == ["fix", "feat", "security"]


def test_verdict_fails_a_conftest_only_change() -> None:
    v = verdict(title="fix: x", production_changed=True, touched=["tests/conftest.py"], changes=[], head={}, base={})
    assert v.status == "fail"


def _write_run(path: Path, exitcode: int) -> Path:
    """Write a pytest-json-report document of a run that ended with ``exitcode`` and ran no test, and return ``path``."""
    path.write_text(json.dumps({"exitcode": exitcode, "tests": [], "collectors": []}))
    return path


def test_incomplete_runs_names_an_absent_report_and_an_aborted_run_and_ignores_an_idle_bucket(tmp_path: Path) -> None:
    unit = FunctionChange("tests/unit/test_a.py", "test_x", CHANGED)
    integration = FunctionChange("tests/integration/test_a.py", "test_y", CHANGED)
    aborted = _write_run(tmp_path / "integration.json", 4)
    reports = {"unit": tmp_path / "absent.json", "integration": aborted}
    assert incomplete_runs("base", reports, [unit, integration]) == [
        "base unit: no report",
        "base integration: pytest exit 4",
    ]
    # A suite with no hosted changed test needs no run, whether its report is aborted or not named at all.
    unit_report = _write_run(tmp_path / "unit.json", 1)
    assert incomplete_runs("base", {"unit": unit_report, "integration": aborted}, [unit]) == []
    assert incomplete_runs("base", {"unit": unit_report}, [unit]) == []
    # A deleted test does not make its suite busy.
    deleted = FunctionChange("tests/integration/test_a.py", "test_old", DELETED)
    assert incomplete_runs("head", {"unit": unit_report}, [unit, deleted]) == []


@pytest.mark.parametrize(
    ("exitcode", "complete"), [(0, True), (1, True), (5, True), (2, False), (3, False), (4, False)]
)
def test_incomplete_runs_accepts_only_the_exit_codes_of_a_run_that_went_through_its_tests(
    tmp_path: Path, exitcode: int, complete: bool
) -> None:
    unit = FunctionChange("tests/unit/test_a.py", "test_x", CHANGED)
    report = _write_run(tmp_path / "unit.json", exitcode)
    assert incomplete_runs("head", {"unit": report}, [unit]) == (
        [] if complete else [f"head unit: pytest exit {exitcode}"]
    )


def test_render_summary_lists_every_change_and_the_untested_touches() -> None:
    text = render_summary(
        title="fix: x",
        verdict=Verdict("fail", "r"),
        touched=["tests/conftest.py", CHANGE.path],
        changes=[CHANGE],
        head={ID: PASSED},
        base={ID: PASSED},
    )
    assert "| tests/unit/test_a.py::test_x | changed | unit | passed | passed |" in text
    assert "tests/conftest.py" in text.split("Touched without a changed test function:")[1]


def test_render_summary_orders_base_before_head_and_dashes_the_tests_that_do_not_run() -> None:
    bdd = FunctionChange("tests/bdd/test_uc.py", "test_s", ADDED)
    gone = FunctionChange("tests/unit/test_a.py", "test_old", DELETED)
    text = render_summary(
        title="fix: x",
        verdict=Verdict("pass", "r"),
        touched=[CHANGE.path, bdd.path, gone.path],
        changes=[CHANGE, bdd, gone],
        head={ID: PASSED},
        base={ID: FAILED},
    )
    assert "| tests/unit/test_a.py::test_x | changed | unit | failed | passed |" in text
    assert "| tests/bdd/test_uc.py::test_s | added | unhosted | - | - |" in text
    assert "| tests/unit/test_a.py::test_old | deleted | unit | - | - |" in text
    assert "Touched without" not in text  # Every touched path holds a change.


def test_render_summary_says_not_collected_for_a_test_of_a_hosted_suite_that_no_run_collected() -> None:
    creative = FunctionChange("tests/integration/test_creative.py", "test_c", CHANGED)
    uncollected = {creative.node_id: NOT_COLLECTED}
    text = render_summary(
        title="fix: x",
        verdict=Verdict("skip", "r"),
        touched=[creative.path],
        changes=[creative],
        head=uncollected,
        base=uncollected,
    )
    assert f"| {creative.node_id} | changed | integration | not collected | not collected |" in text


def test_render_summary_prints_the_title_between_the_heading_and_the_verdict() -> None:
    text = render_summary(title="fix: x", verdict=Verdict("pass", "r"), touched=[], changes=[], head={}, base={})
    assert text.startswith("## Tests redden on base\n\nTitle: fix: x\n\n**pass**: r\n\n| test |")


FIX_ID = "tests/unit/test_a.py::test_one"
INTEGRATION_FIX_ID = "tests/integration/test_a.py::test_one"


def _fix_repo(tmp_path: Path, *suites: str, production: bool = True) -> Path:
    """Return a scratch repo whose HEAD commit changes ``test_one`` in ``tests/<suite>/test_a.py`` of each suite.

    The commit changes ``src/x.py`` too, unless ``production`` is false.
    """
    test_paths = [f"tests/{suite}/test_a.py" for suite in suites]
    repo = git_repo(tmp_path, {"src/x.py": "VALUE = 1\n", **dict.fromkeys(test_paths, "def test_one():\n    pass\n")})
    if production:
        write(repo, "src/x.py", "VALUE = 2\n")
    for test_path in test_paths:
        write(repo, test_path, "def test_one():\n    from src.x import VALUE\n    assert VALUE == 2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "fix")
    return repo


def _changed_json(repo: Path, out: Path) -> Path:
    """Run ``changed`` on ``repo`` against its first parent and return ``out``."""
    assert main(["changed", "--repo", str(repo), "--base", "HEAD^1", "--out", str(out)]) == 0
    return out


def _write_report(path: Path, node_id: str, outcome: str) -> Path:
    """Write a pytest-json-report document with one row, for ``node_id``, and return ``path``."""
    path.write_text(json.dumps({"tests": [{"nodeid": node_id, "outcome": outcome}], "collectors": []}))
    return path


def _changes_json(path: Path, *changes: FunctionChange) -> Path:
    """Write the part of the ``changed`` document that ``ids`` reads, with ``changes`` in the given order."""
    path.write_text(json.dumps({"changes": [asdict(change) for change in changes]}))
    return path


def _verdict_argv(*reports: str, changed: str | Path = "changed.json", summary: str | Path = "summary.md") -> list[str]:
    """Return the arguments of a ``verdict`` call for the title ``fix: x``, followed by the given report options."""
    return ["verdict", "--changed", str(changed), "--title", "fix: x", "--summary", str(summary), *reports]


def test_main_changed_then_ids_then_verdict_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _fix_repo(tmp_path, "unit")  # The base commit has src/x.py and tests/unit/test_a.py::test_one.
    changed = tmp_path / "changed.json"
    assert main(["changed", "--repo", str(repo), "--base", "HEAD^1", "--out", str(changed)]) == 0
    doc = json.loads(changed.read_text())
    assert doc["production_changed"] is True
    assert [c["node_id"] for c in doc["changes"]] == [FIX_ID]
    assert (doc["base"], doc["touched"]) == ("HEAD^1", ["tests/unit/test_a.py"])
    ids = tmp_path / "ids.txt"
    assert main(["ids", str(changed), "unit", "--out", str(ids)]) == 0
    assert (ids.read_text(), capsys.readouterr().out) == (f"{FIX_ID}\n", "tests/unit/test_a.py\n")
    head = _write_report(tmp_path / "head.json", FIX_ID, PASSED)
    base = _write_report(tmp_path / "base.json", FIX_ID, FAILED)
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n")  # The summary file collects what the other steps of the job wrote.
    reports = ("--head-report", f"unit={head}", "--base-report", f"unit={base}")
    assert main(_verdict_argv(*reports, changed=changed, summary=summary)) == 0
    assert capsys.readouterr().out.strip() == f"pass: {FIX_ID} is red on base and green on head"
    text = summary.read_text()
    assert text.startswith("earlier step\n## Tests redden on base\n")
    assert "\nTitle: fix: x\n" in text
    assert f"| {FIX_ID} | changed | unit | failed | passed |" in text


def test_main_verdict_reads_each_suite_from_its_own_report_on_each_side(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changed = _changed_json(_fix_repo(tmp_path, "unit", "integration"), tmp_path / "changed.json")
    summary = tmp_path / "summary.md"
    # Only the integration test is red on the base, so the verdict depends on the report of each suite on each side.
    head_unit = _write_report(tmp_path / "head-unit.json", FIX_ID, PASSED)
    head_integration = _write_report(tmp_path / "head-integration.json", INTEGRATION_FIX_ID, PASSED)
    base_unit = _write_report(tmp_path / "base-unit.json", FIX_ID, PASSED)
    base_integration = _write_report(tmp_path / "base-integration.json", INTEGRATION_FIX_ID, FAILED)
    head = ("--head-report", f"unit={head_unit}", "--head-report", f"integration={head_integration}")
    base = ("--base-report", f"unit={base_unit}", "--base-report", f"integration={base_integration}")
    assert main(_verdict_argv(*head, *base, changed=changed, summary=summary)) == 0
    assert capsys.readouterr().out == f"pass: {INTEGRATION_FIX_ID} is red on base and green on head\n"
    text = summary.read_text()
    assert f"| {FIX_ID} | changed | unit | passed | passed |" in text
    assert f"| {INTEGRATION_FIX_ID} | changed | integration | failed | passed |" in text


def test_main_verdict_errors_when_the_base_report_is_absent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    changed = _changed_json(_fix_repo(tmp_path, "unit"), tmp_path / "changed.json")
    summary = tmp_path / "summary.md"
    head = _write_report(tmp_path / "head.json", FIX_ID, PASSED)
    # A base run that died before it wrote its report must not read as a test that is red on the base.
    reports = ("--head-report", f"unit={head}", "--base-report", f"unit={tmp_path / 'absent-base.json'}")
    assert main(_verdict_argv(*reports, changed=changed, summary=summary)) == 1
    assert capsys.readouterr().out == "error: a run did not complete: base unit: no report\n"
    assert f"| {FIX_ID} | changed | unit | error | passed |" in summary.read_text()


def test_main_verdict_errors_when_a_report_records_an_aborted_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changed = _changed_json(_fix_repo(tmp_path, "unit"), tmp_path / "changed.json")
    head = _write_run(tmp_path / "head.json", 4)
    base = _write_report(tmp_path / "base.json", FIX_ID, FAILED)
    reports = ("--head-report", f"unit={head}", "--base-report", f"unit={base}")
    assert main(_verdict_argv(*reports, changed=changed, summary=tmp_path / "summary.md")) == 1
    assert capsys.readouterr().out == "error: a run did not complete: head unit: pytest exit 4\n"


def test_main_verdict_is_advisory_when_no_production_root_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changed = _changed_json(_fix_repo(tmp_path, "unit", production=False), tmp_path / "changed.json")
    assert json.loads(changed.read_text())["production_changed"] is False
    report = _write_report(tmp_path / "report.json", FIX_ID, PASSED)  # The runs must complete, whatever the verdict is.
    reports = ("--head-report", f"unit={report}", "--base-report", f"unit={report}")
    assert main(_verdict_argv(*reports, changed=changed, summary=tmp_path / "summary.md")) == 0
    assert capsys.readouterr().out == "advisory: no production root changed\n"


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (_verdict_argv("--head-report", "head.json"), "expected BUCKET=PATH"),
        (_verdict_argv("--base-report", "bdd=base.json"), "expected BUCKET=PATH"),
        (_verdict_argv("--head-report", "unit="), "expected BUCKET=PATH"),
        (_verdict_argv("--head-report", "unit=a.json", "--head-report", "unit=b.json"), "'unit' is named twice"),
        (["ids", "changed.json", "bdd"], "invalid choice: 'bdd'"),
        (["ids", "changed.json", "unit"], "the following arguments are required: --out"),
    ],
)
def test_main_refuses_a_bucket_argument_that_is_malformed_or_repeated(
    argv: list[str], reason: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as refused:
        main(argv)
    assert refused.value.code == 2
    assert reason in capsys.readouterr().err


def test_ids_writes_the_bucket_ids_and_prints_their_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The document is not in path order, so the ids keep its order and the printed files do not.
    in_b = FunctionChange("tests/unit/test_b.py", "test_three", ADDED)
    in_a = FunctionChange("tests/unit/test_a.py", "test_one", CHANGED)
    in_a_class = FunctionChange("tests/unit/test_a.py", "TestK.test_two", ADDED)
    integration = FunctionChange("tests/integration/test_c.py", "test_four", ADDED)
    changed = _changes_json(tmp_path / "changed.json", in_b, in_a, integration, in_a_class)
    ids = tmp_path / "ids.txt"
    assert main(["ids", str(changed), "unit", "--out", str(ids)]) == 0
    assert ids.read_text() == f"{in_b.node_id}\n{in_a.node_id}\n{in_a_class.node_id}\n"
    assert capsys.readouterr().out == "tests/unit/test_a.py tests/unit/test_b.py\n"
    assert main(["ids", str(changed), "integration", "--out", str(ids)]) == 0
    assert (ids.read_text(), capsys.readouterr().out) == (f"{integration.node_id}\n", "tests/integration/test_c.py\n")
    # A suite with no test writes an empty file over the earlier one, and prints an empty line.
    no_integration = _changes_json(tmp_path / "no-integration.json", in_b, in_a)
    assert main(["ids", str(no_integration), "integration", "--out", str(ids)]) == 0
    assert (ids.read_text(), capsys.readouterr().out) == ("", "\n")


def test_main_ids_skips_deleted_tests_and_prints_an_empty_line_when_a_suite_has_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path, {"tests/unit/test_a.py": "def test_gone():\n    pass\n"})
    write(repo, "tests/unit/test_a.py", "def test_new():\n    pass\ndef test_other():\n    pass\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "head")
    changed = _changed_json(repo, tmp_path / "changed.json")
    ids = tmp_path / "ids.txt"
    assert main(["ids", str(changed), "unit", "--out", str(ids)]) == 0
    assert ids.read_text() == "tests/unit/test_a.py::test_new\ntests/unit/test_a.py::test_other\n"
    assert capsys.readouterr().out == "tests/unit/test_a.py\n"
    assert main(["ids", str(changed), "integration", "--out", str(ids)]) == 0
    assert (ids.read_text(), capsys.readouterr().out) == ("", "\n")


def test_main_changed_reads_the_current_directory_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(_fix_repo(tmp_path, "unit"))
    out = tmp_path / "changed.json"
    assert main(["changed", "--base", "HEAD^1", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["touched"] == ["tests/unit/test_a.py"]


def test_main_changed_writes_gits_message_to_stderr_before_it_raises(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path, {"README.md": "x\n"})
    with pytest.raises(subprocess.CalledProcessError):
        main(["changed", "--repo", str(repo), "--base", "no-such-ref", "--out", str(tmp_path / "changed.json")])
    assert "no-such-ref" in capsys.readouterr().err


def test_main_run_as_a_module_exits_with_the_code_of_the_verdict(tmp_path: Path) -> None:
    changed = _changed_json(_fix_repo(tmp_path, "unit"), tmp_path / "changed.json")
    command = [
        sys.executable,
        "-m",
        "scripts.ci.redden_on_base",
        *_verdict_argv(changed=changed, summary=tmp_path / "s.md"),
    ]
    run = subprocess.run(command, cwd=repo_root(), capture_output=True, text=True)
    # With no report, neither run completed, so the verdict is an error, and an error exits 1.
    reason = "a run did not complete: head unit: no report; base unit: no report"
    assert (run.returncode, run.stdout) == (1, f"error: {reason}\n")
