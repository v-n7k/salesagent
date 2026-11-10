"""Tests for the ``--only-ids`` plugin of the red-on-base gate, which a pytest subprocess loads with ``-p``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.ci.redden_on_base import ERROR, PASSED, outcomes
from tests.unit._architecture_helpers import repo_root

# On the base, a test module that imports a symbol the pull request added cannot import.
BAD_MODULE = """\
import nonexistent_module_for_this_test


def test_a():
    pass
"""

GOOD_MODULE = """\
import pytest


def test_b():
    pass


def test_c():
    assert False


@pytest.mark.parametrize("value", [1, 2])
def test_p(value):
    pass
"""


def test_plugin_runs_the_listed_tests_and_tolerates_a_module_that_cannot_import(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\n")  # The rootdir is tmp_path, whatever its parents hold.
    (tests / "test_bad.py").write_text(BAD_MODULE)
    (tests / "test_good.py").write_text(GOOD_MODULE)
    wanted = ["tests/test_bad.py::test_a", "tests/test_good.py::test_b", "tests/test_good.py::test_p"]
    ids = tmp_path / "ids.txt"
    ids.write_text("".join(f"{node_id}\n" for node_id in wanted))
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_bad.py",
        "tests/test_good.py",
        "-p",
        "scripts.ci.pytest_only_ids",
        "--only-ids",
        str(ids),
        "-p",
        "no:randomly",
        "-p",
        "no:cacheprovider",
        "-q",
        "--tb=line",
        "--continue-on-collection-errors",
        "--json-report",
        "--json-report-file=report.json",
    ]
    env = {**os.environ, "PYTHONPATH": str(repo_root())}
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=300)

    # Exit 1 is a failed collector. A test module that cannot import must not end the run with a usage error (4).
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert (tmp_path / "report.json").exists(), output  # A plugin that fails to import also exits 1, with no report.
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["exitcode"] == 1
    # ``test_c`` is not listed, so it is deselected. The parameter sets of ``test_p`` both run.
    assert report["summary"].get("deselected") == 1
    assert [(row["nodeid"], row["outcome"]) for row in report["tests"]] == [
        ("tests/test_good.py::test_b", "passed"),
        ("tests/test_good.py::test_p[1]", "passed"),
        ("tests/test_good.py::test_p[2]", "passed"),
    ]
    assert [c["nodeid"] for c in report["collectors"] if c["outcome"] == "failed"] == ["tests/test_bad.py"]
    assert outcomes(report, wanted) == {
        "tests/test_bad.py::test_a": ERROR,
        "tests/test_good.py::test_b": PASSED,
        "tests/test_good.py::test_p": PASSED,
    }
