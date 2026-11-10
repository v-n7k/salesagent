"""Guard: every test suite run_all_tests.sh exercises must gate CI.

Regression coverage for the post-PR-#1299 silent-breakage gap: PR #1299
merged with CI green, yet ``./run_all_tests.sh`` immediately showed 12 BDD +
32 E2E failures on main. Root cause: the BDD suite had **zero** CI coverage
(no job in ``.github/workflows/ci.yml``), and the aggregation/gating job
must propagate BDD/E2E failures so a red suite turns CI red.

This is a configuration-contract assertion: the workflow file is parsed as
YAML data and the job graph is inspected. It is NOT a source-code AST scan.

No allowlist — zero tolerance. Every locally-run suite must have a gating
CI job, or a broken suite can silently land on main again.
"""

import pytest

from scripts.ci.workflow_helpers import load_ci_workflow

# Suite jobs that must appear in summary.needs — a suite that runs but is absent
# from summary.needs leaves CI green on its failure (PR #1299 silent-breakage class).
REQUIRED_SUMMARY_GATES = frozenset({"unit-tests", "integration-tests", "e2e-tests", "bdd-tests", "admin-ui-tests"})


def _assert_job_uploads_coverage(
    job: dict, *, artifact: str, data_file: str, xml: str, pytest_if: str | None = None
) -> dict:
    """Assert that one `_pytest` step writes `data_file` and `xml`, and one upload named `artifact` carries both.

    `pytest_if` narrows the `_pytest` steps to those whose `if` equals it; None counts every `_pytest` step.
    Returns the upload step, so a caller can assert what is specific to its job.
    """
    pytest_steps = [
        step
        for step in job["steps"]
        if str(step.get("uses", "")).endswith("/_pytest") and (pytest_if is None or step.get("if") == pytest_if)
    ]
    assert len(pytest_steps) == 1, f"expected one _pytest step (if={pytest_if!r}), found {len(pytest_steps)}"
    assert pytest_steps[0].get("env", {}).get("COVERAGE_FILE") == data_file, "the suite must write its own data file"
    assert pytest_steps[0].get("with", {}).get("coverage_xml") == xml, "the suite must write its own XML report"
    uploads = [
        step
        for step in job["steps"]
        if "actions/upload-artifact" in str(step.get("uses", "")) and step.get("with", {}).get("name") == artifact
    ]
    assert len(uploads) == 1, f"expected one upload named {artifact!r}, found {len(uploads)}"
    upload = uploads[0]
    assert "always()" in str(upload.get("if", "")), "the upload must run when the suite fails, or its data is lost"
    assert data_file in upload["with"].get("path", ""), "the upload must carry the data file"
    assert xml in upload["with"].get("path", ""), "the upload must carry the XML report"
    assert upload["with"].get("include-hidden-files") is True, "the data file is a dotfile; upload skips it otherwise"
    assert upload["with"].get("if-no-files-found") == "error", "a missing data file must fail the upload, not warn"
    return upload


class TestCISuiteCoverage:
    """BDD and E2E suites must run in CI and gate the test summary."""

    @pytest.mark.arch_guard
    def test_bdd_job_exists(self):
        """BDD aggregate + parallel shard jobs must exist in CI."""
        jobs = load_ci_workflow()["jobs"]

        assert "bdd-tests" in jobs, "No 'bdd-tests' aggregate job in .github/workflows/ci.yml."
        assert "bdd-tests-shard" in jobs, "No 'bdd-tests-shard' matrix job in .github/workflows/ci.yml."

    @pytest.mark.arch_guard
    def test_bdd_shards_run_the_bdd_suite(self):
        """Each BDD shard must resolve paths via shard_paths and run pytest."""
        shard_job = load_ci_workflow()["jobs"]["bdd-tests-shard"]
        steps_text = " ".join(
            str(step.get("run", "")) + " " + str(step.get("uses", "")) + " " + str(step.get("with", {}))
            for step in shard_job.get("steps", [])
        )

        assert "shard_paths.py bdd" in steps_text, (
            "bdd-tests-shard must resolve test files via scripts/ci/shard_paths.py bdd."
        )
        assert "./.github/actions/_pytest" in steps_text or "pytest" in steps_text, (
            "bdd-tests-shard must invoke pytest (via _pytest composite or explicit run)."
        )

    @pytest.mark.arch_guard
    def test_bdd_shards_have_postgres_service(self):
        """BDD harnesses use the integration_db fixture (real PostgreSQL)."""
        services = load_ci_workflow()["jobs"]["bdd-tests-shard"].get("services", {})

        assert "postgres" in services, "bdd-tests-shard has no postgres service."

    @pytest.mark.arch_guard
    def test_bdd_aggregate_is_status_proxy_only(self):
        """Aggregate BDD job must gate shard status, not merge coverage."""
        aggregate = load_ci_workflow()["jobs"]["bdd-tests"]
        steps_text = " ".join(str(step.get("run", "")) for step in aggregate.get("steps", []))
        assert "needs.bdd-tests-shard.result" in steps_text, "bdd-tests aggregate must fail when bdd-tests-shard fails."
        assert "coverage combine" not in steps_text, (
            "bdd-tests aggregate must not merge coverage; that belongs in the Coverage job."
        )

    @pytest.mark.arch_guard
    def test_admin_job_has_postgres_service(self):
        """Admin blueprint tests use integration_db and require PostgreSQL."""
        admin_job = load_ci_workflow()["jobs"]["admin-ui-tests"]
        services = admin_job.get("services", {})

        assert "postgres" in services, (
            "The 'admin-ui-tests' job has no 'postgres' service. Admin tests use "
            "the integration_db fixture and require a real PostgreSQL instance."
        )

    @pytest.mark.arch_guard
    def test_integration_job_uses_entity_shards(self):
        """Integration tests must run in parallel entity shards (legacy parity)."""
        integration_job = load_ci_workflow()["jobs"]["integration-tests"]
        matrix = integration_job.get("strategy", {}).get("matrix", {})
        include = matrix.get("include", [])
        groups = {row["group"] for row in include}

        assert groups == {"creative", "product", "media-buy", "infra", "other"}, (
            "integration-tests must shard by entity marker groups to keep CI wall time bounded."
        )

        step_text = " ".join(
            str(step.get("run", "")) + " " + str(step.get("with", {}).get("extra_args", ""))
            for step in integration_job.get("steps", [])
        )
        assert "matrix.marker" in step_text, (
            "integration-tests must filter pytest with matrix.marker, not run the full suite serially."
        )

    @pytest.mark.arch_guard
    def test_integration_shards_use_strict_partition(self):
        """Shards 2–4 must exclude earlier shard markers to avoid duplicate runs."""
        integration_job = load_ci_workflow()["jobs"]["integration-tests"]
        markers = {row["group"]: row["marker"] for row in integration_job["strategy"]["matrix"]["include"]}

        assert markers["creative"] == "creative"
        assert "and not creative" in markers["product"]
        assert "and not creative" in markers["media-buy"]
        assert "and not product" in markers["media-buy"]
        assert "and not creative" in markers["infra"]
        assert "and not product" in markers["infra"]
        assert "and not media_buy" in markers["infra"]
        assert "and not delivery" in markers["infra"]

    @pytest.mark.arch_guard
    def test_host_integration_groups_upload_coverage(self):
        """Every host integration group writes its own data file and uploads it; creative uploads no coverage."""
        from scripts.ci.shard_split import INTEGRATION_HOST_GROUPS

        job = load_ci_workflow()["jobs"]["integration-tests"]
        groups = {row["group"] for row in job["strategy"]["matrix"]["include"]}
        assert groups - {"creative"} == set(INTEGRATION_HOST_GROUPS), (
            "the matrix's host groups and shard_split.INTEGRATION_HOST_GROUPS must be the same list; "
            "the coverage gate loops over the constant"
        )
        upload = _assert_job_uploads_coverage(
            job,
            artifact="integration-${{ matrix.group }}-coverage",
            data_file=".coverage.integration-${{ matrix.group }}",
            xml="coverage-integration-${{ matrix.group }}.xml",
            pytest_if="matrix.group != 'creative'",
        )
        assert "matrix.group != 'creative'" in str(upload.get("if", "")), "the creative group must upload no coverage"

    @pytest.mark.arch_guard
    def test_admin_job_uploads_coverage(self):
        """The admin suite writes its own data file and uploads it for the Coverage job to combine."""
        _assert_job_uploads_coverage(
            load_ci_workflow()["jobs"]["admin-ui-tests"],
            artifact="admin-coverage",
            data_file=".coverage.admin",
            xml="coverage-admin.xml",
        )

    @pytest.mark.arch_guard
    def test_coverage_gate_requires_every_host_suite_artifact(self):
        """A missing data file fails the gate by name; a partial combine would report a lower number as the truth."""
        job = load_ci_workflow()["jobs"]["coverage"]
        run_steps = " ".join(str(step.get("run", "")) for step in job["steps"])
        assert "INTEGRATION_HOST_GROUPS" in run_steps, "the gate loops over shard_split.INTEGRATION_HOST_GROUPS"
        assert "Missing integration coverage artifact for group" in run_steps
        assert "Missing admin coverage artifact" in run_steps
        assert '"${bdd_data_files[@]}" "${integration_data_files[@]}" admin-coverage/.coverage.admin' in run_steps, (
            "the combine must name every suite's data file"
        )
        downloads = [
            step.get("with", {}) for step in job["steps"] if "actions/download-artifact" in str(step.get("uses", ""))
        ]
        assert any(
            w.get("pattern") == "integration-*-coverage" and w.get("path") == "integration-coverage-groups"
            for w in downloads
        )
        assert any(w.get("name") == "admin-coverage" and w.get("path") == "admin-coverage" for w in downloads)
        assert "needs.integration-tests.result == 'success'" in str(job["if"])
        assert "needs.admin-ui-tests.result == 'success'" in str(job["if"])

    @pytest.mark.arch_guard
    def test_coverage_job_reports_diff_coverage(self):
        """The report is computed against HEAD^1 on a two-commit checkout and lands in the step summary."""
        job = load_ci_workflow()["jobs"]["coverage"]
        checkout = next(step for step in job["steps"] if "actions/checkout" in str(step.get("uses", "")))
        assert checkout["with"]["fetch-depth"] == 2, "HEAD^1 (the PR base) must be in the clone"
        run_steps = " ".join(str(step.get("run", "")) for step in job["steps"])
        assert "coverage xml --data-file=.coverage.combined -o coverage-combined.xml" in run_steps
        assert "uv run diff-cover coverage-combined.xml --compare-branch=HEAD^1 --diff-range-notation=.." in run_steps
        assert "--format markdown:diff-cover.md" in run_steps
        assert "--fail-under" not in run_steps, "stage 1 is report only; the threshold is stage 2"
        assert 'diff-cover.md >> "$GITHUB_STEP_SUMMARY"' in run_steps
        upload = next(
            step["with"]
            for step in job["steps"]
            if "actions/upload-artifact" in str(step.get("uses", "")) and step["with"].get("name") == "diff-cover"
        )
        assert "diff-cover.md" in upload["path"] and "coverage-combined.xml" in upload["path"], (
            "the artifact carries the report and the XML it was computed from"
        )
        assert upload.get("if-no-files-found") == "error", "a missing report must fail the upload, not warn"

    @pytest.mark.arch_guard
    def test_coverage_floor_runs_last(self):
        """The floor is the last step, so the diff-cover report and its artifact exist on a run under the floor."""
        job = load_ci_workflow()["jobs"]["coverage"]
        assert job["steps"][-1].get("name") == "Coverage floor", "nothing enforces .coverage-baseline without this step"
        assert job["steps"][-1]["run"].strip() == "./scripts/ci/coverage_report.sh --data-file .coverage.combined"

    @pytest.mark.arch_guard
    def test_quality_gate_does_not_run_unit_tests(self):
        """Quality Gate runs static checks only; unit tests run once in unit-tests."""
        quality_job = load_ci_workflow()["jobs"]["quality-gate"]
        run_steps = " ".join(str(step.get("run", "")) for step in quality_job.get("steps", []))

        assert "make quality-ci" in run_steps, "quality-gate must invoke make quality-ci (no pytest)."
        assert "pytest" not in run_steps, "quality-gate must not re-run unit tests."

    @pytest.mark.arch_guard
    def test_coverage_job_reuses_test_artifacts(self):
        """Coverage gate must not re-run pytest; it combines the unit, BDD, integration and admin artifacts."""
        coverage_job = load_ci_workflow()["jobs"]["coverage"]
        needs = coverage_job.get("needs", [])
        steps_text = " ".join(
            str(step.get("name", "")) + " " + str(step.get("uses", "")) for step in coverage_job.get("steps", [])
        )

        assert "unit-tests" in needs, "coverage job must depend on unit-tests."
        assert "bdd-tests-shard" in needs, "coverage job must depend on bdd-tests-shard."
        assert "integration-tests" in needs, "coverage job must depend on integration-tests."
        assert "admin-ui-tests" in needs, "coverage job must depend on admin-ui-tests."
        assert steps_text.count("download-artifact") == 4, (
            "coverage job must download exactly the unit, BDD shard, integration group and admin coverage artifacts."
        )
        run_steps = " ".join(str(step.get("run", "")) for step in coverage_job.get("steps", []))
        assert "pytest" not in run_steps, "coverage job must not re-run tests."
        assert "coverage combine" in run_steps, "coverage job must combine every suite's coverage data."

    @pytest.mark.arch_guard
    def test_coverage_gate_requires_all_bdd_shard_artifacts(self):
        """Coverage must fail on partial BDD shard artifact sets, not combine survivors."""
        coverage_job = load_ci_workflow()["jobs"]["coverage"]
        run_steps = " ".join(str(step.get("run", "")) for step in coverage_job.get("steps", []))

        assert "SHARD_COUNTS" in run_steps, "coverage gate must read SHARD_COUNTS from shard_split."
        assert "expected_bdd_shards" in run_steps, "coverage gate must bind BDD shard count to a variable."
        assert "Missing BDD coverage artifact for shard" in run_steps, (
            "coverage gate must fail when any shard's .coverage.bdd-N file is missing."
        )
        assert 'bdd_shards="$(seq 1 "${expected_bdd_shards}")"' in run_steps, (
            "the shard ids are bound before the call, so a failing seq stops the step under set -e"
        )
        assert "no ids to collect" in run_steps, "an empty id list must fail the step, not combine nothing"
        bdd_downloads = [
            step.get("with", {})
            for step in coverage_job.get("steps", [])
            if step.get("with", {}).get("pattern") == "bdd-shard-*-coverage"
        ]
        assert bdd_downloads, "coverage job must download BDD shard artifacts via bdd-shard-*-coverage pattern."
        assert bdd_downloads[0].get("path") == "bdd-coverage-shards", (
            "BDD shard coverage artifacts must land under bdd-coverage-shards/."
        )

    @pytest.mark.arch_guard
    def test_ci_jobs_declare_permissions_and_timeout(self):
        """Every CI job must declare permissions and timeout (workflow hygiene)."""
        jobs = load_ci_workflow()["jobs"]
        missing: list[str] = []
        for job_name, job in jobs.items():
            if "permissions" not in job:
                missing.append(f"{job_name}: permissions")
            if "timeout-minutes" not in job:
                missing.append(f"{job_name}: timeout-minutes")
        assert not missing, "CI jobs missing hygiene fields:\n" + "\n".join(f"  - {m}" for m in missing)

    @pytest.mark.arch_guard
    def test_summary_gates_every_required_job(self):
        """summary must include every suite gate AND fail for every job in summary.needs."""
        workflow = load_ci_workflow()
        summary = workflow["jobs"]["summary"]
        needs = summary["needs"]
        check_text = " ".join(str(step.get("run", "")) for step in summary.get("steps", []))

        assert isinstance(needs, list) and needs, "summary.needs must list every upstream gate job."
        missing = REQUIRED_SUMMARY_GATES - set(needs)
        assert not missing, (
            f"summary.needs dropped required suite gate(s) {sorted(missing)}. A suite that runs but is "
            "absent from summary.needs leaves CI green on its failure."
        )
        for required in needs:
            assert required in workflow["jobs"], (
                f"summary.needs lists unknown job '{required}'. Update summary.needs or add the missing job definition."
            )
            token = f"needs.{required}.result"
            assert token in check_text, (
                f"summary's result-check step does not inspect '{token}'. "
                f"A failing {required} job would not fail CI even though it is listed in needs[]."
            )

    @pytest.mark.arch_guard
    def test_type_check_uses_make_target(self):
        """Type Check job must invoke the same entrypoint as local make typecheck."""
        type_check = load_ci_workflow()["jobs"]["type-check"]
        run_steps = " ".join(str(step.get("run", "")) for step in type_check.get("steps", []))
        assert "make typecheck" in run_steps, "type-check job must run make typecheck for CI/local parity."

    @pytest.mark.arch_guard
    def test_smoke_tests_do_not_duplicate_skip_guard(self):
        """Skip-decorator enforcement belongs in the smoke suite, not a workflow grep step."""
        smoke_job = load_ci_workflow()["jobs"]["smoke-tests"]
        step_text = " ".join(f"{step.get('name', '')} {step.get('run', '')}" for step in smoke_job.get("steps", []))
        skip_marker = "@" + "pytest" + ".mark.skip"
        assert skip_marker not in step_text, (
            "smoke-tests must not grep for skip decorators in a workflow step; "
            "TestNoSkippedTests is the single source of truth."
        )

    @pytest.mark.arch_guard
    def test_skip_guard_single_source_of_truth_exists(self):
        """The SSoT the workflow delegates to must exist, or enforcement is unguarded."""
        from tests.smoke.test_smoke_basic import TestNoSkippedTests

        assert hasattr(TestNoSkippedTests, "test_no_skip_decorators"), (
            "TestNoSkippedTests.test_no_skip_decorators is the declared single source of truth for skip enforcement."
        )

    @pytest.mark.arch_guard
    def test_bdd_and_e2e_run_on_pull_request(self):
        """The gate is worthless if it doesn't run on PRs.

        Cost-aware: it must reuse the existing pull_request trigger, not add
        new triggers.
        """
        workflow = load_ci_workflow()
        # PyYAML parses the bare ``on:`` key as the boolean True.
        triggers = workflow.get("on", workflow.get(True))

        assert "pull_request" in triggers, (
            "The CI workflow does not trigger on pull_request, so BDD/E2E gating would never run before merge."
        )
