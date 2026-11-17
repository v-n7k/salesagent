"""Contract test for scripts/ci/collect_coverage_data.sh, run the way the Coverage job runs it.

The script names the data files the Coverage job combines, in combine order, one per line, and refuses a
missing one by name with the ``::error::`` line the checks UI shows. Each case lays the job's download
layout out under ``tmp_path`` and runs the script there, so a case grades the script and nothing else.
"""

import subprocess
from pathlib import Path

from scripts.ci.shard_split import INTEGRATION_HOST_GROUPS, SHARD_COUNTS
from scripts.ci.workflow_helpers import CI_WORKFLOW_PATH

SCRIPT = CI_WORKFLOW_PATH.parents[2] / "scripts" / "ci" / "collect_coverage_data.sh"
# The ids the workflow passes: seq output for the shards (newline separated), the tuple joined by spaces.
BDD_SHARDS = "\n".join(str(shard) for shard in range(1, SHARD_COUNTS["bdd"] + 1))
HOST_GROUPS = " ".join(INTEGRATION_HOST_GROUPS)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _layout(root: Path, *, shards: str = BDD_SHARDS, groups: str = HOST_GROUPS, unit=True, admin=True) -> None:
    """Lay out the Coverage job's downloads: the unit file at the root, the other suites under their directories."""
    if unit:
        _touch(root / ".coverage")
    for shard in shards.split():
        _touch(root / "bdd-coverage-shards" / f".coverage.bdd-{shard}")
    for group in groups.split():
        _touch(root / "integration-coverage-groups" / f".coverage.integration-{group}")
    if admin:
        _touch(root / "admin-coverage" / ".coverage.admin")


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Invoked by path, as the workflow does, so a lost executable bit fails here and not in the job.
    return subprocess.run([str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, timeout=30, check=False)


def _collect(cwd: Path, *, shards: str = BDD_SHARDS, groups: str = HOST_GROUPS) -> subprocess.CompletedProcess[str]:
    return _run(cwd, "--bdd-shards", shards, "--host-groups", groups)


def test_every_file_present_lists_the_ten_data_files_in_combine_order(tmp_path):
    _layout(tmp_path)

    proc = _collect(tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert proc.stdout.splitlines() == [
        ".coverage",
        *[f"bdd-coverage-shards/.coverage.bdd-{shard}" for shard in BDD_SHARDS.split()],
        *[f"integration-coverage-groups/.coverage.integration-{group}" for group in HOST_GROUPS.split()],
        "admin-coverage/.coverage.admin",
    ]
    assert len(proc.stdout.splitlines()) == 10


def test_one_shard_file_missing_fails_by_shard_id(tmp_path):
    _layout(tmp_path, shards="1 2 4")

    proc = _collect(tmp_path)

    assert proc.returncode == 1
    assert proc.stderr == "::error::Missing BDD coverage artifact for shard 3 (.coverage.bdd-3)\n"
    assert proc.stdout == "", "nothing is listed on a failure, so a caller cannot combine a partial set"


def test_empty_shard_id_list_fails_instead_of_collecting_nothing(tmp_path):
    _layout(tmp_path)

    proc = _collect(tmp_path, shards="")

    assert proc.returncode == 1
    assert proc.stderr == "::error::Missing BDD coverage artifact for shard: no ids to collect\n"
    assert proc.stdout == ""


def test_unit_file_missing_fails(tmp_path):
    _layout(tmp_path, unit=False)

    proc = _collect(tmp_path)

    assert proc.returncode == 1
    assert proc.stderr == "::error::Unit coverage data file missing.\n"
    assert proc.stdout == ""


def test_one_group_file_missing_fails_by_group_name(tmp_path):
    _layout(tmp_path, groups="product infra other")

    proc = _collect(tmp_path)

    assert proc.returncode == 1
    assert (
        proc.stderr
        == "::error::Missing integration coverage artifact for group media-buy (.coverage.integration-media-buy)\n"
    )
    assert proc.stdout == ""


def test_admin_file_missing_fails(tmp_path):
    _layout(tmp_path, admin=False)

    proc = _collect(tmp_path)

    assert proc.returncode == 1
    assert proc.stderr == "::error::Missing admin coverage artifact (.coverage.admin)\n"
    assert proc.stdout == ""


def test_missing_flag_is_a_usage_error(tmp_path):
    _layout(tmp_path)

    proc = _run(tmp_path, "--bdd-shards", BDD_SHARDS)

    assert proc.returncode == 1
    assert proc.stderr.startswith("Usage:")
    assert proc.stdout == ""
