"""Tests for the clone-count ratchet hook (``.pre-commit-hooks/check_clone_count.py``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci.clone_index import index_tree
from tests.unit._architecture_helpers import load_hook_module
from tests.unit._clone_index_helpers import SEED_A, SEED_B, write_sources

NO_CLONES = {"src": 0, "tests": 0, "scripts": 0, ".pre-commit-hooks": 0, ".claude/scripts": 0}


@pytest.fixture(scope="module")
def hook():
    return load_hook_module("check_clone_count")


def test_count_has_every_root_and_zero_for_absent_roots(hook, tmp_path: Path) -> None:
    write_sources(tmp_path, {"src/a.py": SEED_A})
    assert hook.count_clone_bearing(tmp_path) == NO_CLONES


def test_count_pairs_across_roots(hook, tmp_path: Path) -> None:
    write_sources(tmp_path, {"src/a.py": SEED_A, ".claude/scripts/b.py": SEED_B})
    assert hook.count_clone_bearing(tmp_path) == {**NO_CLONES, "src": 1, ".claude/scripts": 1}


def test_no_hints_when_nothing_rose(hook, tmp_path: Path) -> None:
    assert hook.hints_for_increase(tmp_path, {}, {"src": 3, "tests": 1}, {"src": 3, "tests": 0}) == []


def test_no_hints_before_a_baseline_exists(hook, tmp_path: Path) -> None:
    assert hook.hints_for_increase(tmp_path, {}, None, {"src": 3, "tests": 1}) == []


def test_hints_name_the_new_pair_even_when_the_total_fell(hook, monkeypatch, tmp_path: Path) -> None:
    base_root, head_root = tmp_path / "base", tmp_path / "head"
    # Three copies, all under src.
    base = {"src/a.py": SEED_A, "src/b.py": SEED_B, "src/d.py": SEED_B.replace("seed_other", "seed_fourth")}
    # Two copies: src fell 3 -> 1, tests rose 0 -> 1.
    head = {"src/a.py": SEED_A, "tests/c.py": SEED_B.replace("seed_other", "seed_third")}
    write_sources(base_root, base)
    write_sources(head_root, head)
    monkeypatch.setattr(hook, "materialize_upstream_tree", lambda repo_root, paths, dest: base_root)
    lines = hook.hints_for_increase(head_root, index_tree(head_root), {"src": 3, "tests": 0}, {"src": 1, "tests": 1})
    # After the three fixed lines, only the new copy. seed_tenant was clone-bearing in base already.
    assert lines[3:] == ["  tests/c.py:1 seed_third  <->  src/a.py:1 seed_tenant"]


def test_hints_without_an_upstream_ref_are_the_fixed_lines(hook, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hook, "materialize_upstream_tree", lambda repo_root, paths, dest: None)
    lines = hook.hints_for_increase(tmp_path, {}, {"src": 0}, {"src": 1})
    assert lines[0].startswith("Extract the shared statements")
    assert len(lines) == 3
