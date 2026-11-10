"""Tests for the clone-count ratchet hook (``.pre-commit-hooks/check_clone_count.py``)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from scripts.ci.clone_index import ROOTS, index_tree
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

    def materialize(_repo_root, paths, _dest):
        assert tuple(paths) == ROOTS
        return base_root

    monkeypatch.setattr(hook, "materialize_upstream_tree", materialize)
    lines = hook.hints_for_increase(head_root, index_tree(head_root), {"src": 3, "tests": 0}, {"src": 1, "tests": 1})
    # After the three fixed lines, only the new copy. seed_tenant was clone-bearing in base already.
    assert lines[3:] == ["  tests/c.py:1 seed_third  <->  src/a.py:1 seed_tenant"]


def test_hints_without_an_upstream_ref_are_the_fixed_lines(hook, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hook, "materialize_upstream_tree", lambda repo_root, paths, dest: None)
    lines = hook.hints_for_increase(tmp_path, {}, {"src": 0}, {"src": 1})
    assert lines[0].startswith("Extract the shared statements")
    assert len(lines) == 3


def _fail_archive(*_args: object) -> Path:
    raise RuntimeError("git archive deadbeef failed")


def test_hints_survive_a_failed_upstream_extraction(hook, monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(hook, "materialize_upstream_tree", _fail_archive)
    lines = hook.hints_for_increase(tmp_path, {}, {"src": 0}, {"src": 1})
    assert len(lines) == 3
    assert "could not name the new clone pairs" in capsys.readouterr().err


def _run_main(hook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[int, dict[str, Any]]:
    """Run ``hook.main()`` over an empty tree with the driver stubbed out.

    Returns the exit code and the keyword arguments ``main`` passed to ``run_count_ratchet``.
    """
    seen: dict[str, Any] = {}
    monkeypatch.setattr(hook, "run_count_ratchet", lambda **kwargs: seen.update(kwargs) or 0)
    monkeypatch.setattr(
        hook, "resolve_ratchet_paths", lambda *, baseline_name: (tmp_path, tmp_path / "src", tmp_path / baseline_name)
    )
    monkeypatch.setattr(hook, "parse_ratchet_args", lambda _description: argparse.Namespace(update_baseline=False))
    monkeypatch.setattr(hook, "index_tree", lambda _root: {})
    return hook.main(), seen


def test_main_wires_the_roots_into_the_driver(hook, monkeypatch, tmp_path: Path) -> None:
    rc, kwargs = _run_main(hook, monkeypatch, tmp_path)
    assert (rc, kwargs["keys"], kwargs["upstream_paths"]) == (0, ROOTS, ROOTS)
    assert kwargs["count_upstream"] is hook.count_clone_bearing
    assert (kwargs["current"], kwargs["baseline_file"]) == (NO_CLONES, tmp_path / ".clone-baseline")
