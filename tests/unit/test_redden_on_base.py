"""Tests for the verdict of the red-on-base gate: the outcome of each test, the rules in order, and the summary."""

from __future__ import annotations

from scripts.ci.changed_functions import ADDED, CHANGED, DELETED, FunctionChange
from scripts.ci.redden_on_base import (
    ERROR,
    FAILED,
    NOT_COLLECTED,
    PASSED,
    SKIPPED,
    Verdict,
    bucket_for,
    outcomes,
    render_summary,
    title_prefix,
    verdict,
)


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
    assert [_status(FAILED, on_head) for on_head in (SKIPPED, NOT_COLLECTED, ERROR, None)] == ["fail"] * 4
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
