"""Tests for the changed-test set that the red-on-base gate reruns against the base branch."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.ci.changed_functions import (
    ADDED,
    CHANGED,
    DELETED,
    FunctionChange,
    changed_test_functions,
    collectable_tests,
    diff_functions,
    function_fingerprints,
)
from tests.helpers.scratch_repo import git, git_repo, write


def test_collectable_tests_follows_pytest_ini_rules() -> None:
    tree = ast.parse(
        "def test_a():\n    def test_inner():\n        pass\ndef helper():\n    pass\nclass TestB:\n    def test_m(self):\n        pass\n    def util(self):\n        pass\n    class TestC:\n        def test_n(self):\n            pass\nclass Other:\n    def test_x(self):\n        pass\n"
    )
    assert sorted(collectable_tests(tree)) == ["TestB.TestC.test_n", "TestB.test_m", "test_a"]


def test_diff_functions_classifies_added_changed_deleted() -> None:
    base = "def test_same():\n    assert 1\ndef test_gone():\n    assert 2\ndef test_edit():\n    assert a == 1\n"
    # The head changes the operator, because a literal-only edit leaves the shape the same.
    head = "def test_same():\n    assert 1\ndef test_new():\n    assert 3\ndef test_edit():\n    assert a != 1\n"
    assert diff_functions(base, head, "tests/unit/test_x.py") == [
        FunctionChange("tests/unit/test_x.py", "test_edit", CHANGED),
        FunctionChange("tests/unit/test_x.py", "test_gone", DELETED),
        FunctionChange("tests/unit/test_x.py", "test_new", ADDED),
    ]


def test_diff_functions_ignores_rename_docstring_and_literal_only_edits() -> None:
    base = 'def test_x():\n    """old"""\n    value = make(1)\n    assert value == "a"\n'
    head = 'def test_x():\n    """new"""\n    result = make(2)\n    assert result == "b"\n'
    assert diff_functions(base, head, "tests/unit/test_x.py") == []


def test_diff_functions_treats_a_missing_side_as_empty() -> None:
    assert diff_functions(None, "def test_a():\n    pass\n", "p.py") == [FunctionChange("p.py", "test_a", ADDED)]
    assert diff_functions("def test_a():\n    pass\n", None, "p.py") == [FunctionChange("p.py", "test_a", DELETED)]


def test_function_fingerprints_names_the_file_on_a_syntax_error() -> None:
    with pytest.raises(SyntaxError, match="tests/unit/test_bad.py"):
        function_fingerprints("def test_(:\n", "tests/unit/test_bad.py")


def test_node_id_uses_pytest_separators() -> None:
    change = FunctionChange("tests/unit/test_x.py", "TestB.test_m", CHANGED)
    assert change.node_id == "tests/unit/test_x.py::TestB::test_m"


def test_changed_test_functions_reads_both_sides_from_git(tmp_path: Path) -> None:
    base_files = {
        "tests/unit/test_a.py": "def test_one():\n    pass\n",
        "tests/unit/test_c.py": "def test_four():\n    assert 4\n",
        "tests/conftest.py": "",
    }
    repo = git_repo(tmp_path, base_files)
    write(repo, "tests/unit/test_a.py", "def test_one():\n    assert 2\ndef test_two():\n    assert 1\n")
    write(repo, "tests/unit/test_b.py", "def test_three():\n    assert 1\n")  # The head adds this file.
    git(repo, "mv", "tests/conftest.py", "tests/conftest2.py")  # A rename reads as a deletion plus an addition.
    git(repo, "mv", "tests/unit/test_c.py", "tests/unit/test_d.py")  # So does the rename of a test module.
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "head")
    touched, changes = changed_test_functions(repo, "HEAD^1")
    assert touched == [
        "tests/conftest.py",
        "tests/conftest2.py",
        "tests/unit/test_a.py",
        "tests/unit/test_b.py",
        "tests/unit/test_c.py",
        "tests/unit/test_d.py",
    ]
    assert changes == [
        FunctionChange("tests/unit/test_a.py", "test_one", CHANGED),
        FunctionChange("tests/unit/test_a.py", "test_two", ADDED),
        FunctionChange("tests/unit/test_b.py", "test_three", ADDED),
        FunctionChange("tests/unit/test_c.py", "test_four", DELETED),  # The old path of the renamed module.
        FunctionChange("tests/unit/test_d.py", "test_four", ADDED),  # The new path of the renamed module.
    ]
