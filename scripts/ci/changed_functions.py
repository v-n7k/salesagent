"""List the test functions that a pull request added, deleted, or changed.

The red-on-base gate reruns these tests against the production code of the base branch. A test
counts as changed when its normalized shape differs, as ``function_fingerprint`` computes it.
Renaming the test or its local variables, rewording a docstring, and changing a literal value
leave the shape the same.
"""

from __future__ import annotations

import ast
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scripts.ci.ast_normalize import function_fingerprint

ADDED = "added"
CHANGED = "changed"
DELETED = "deleted"

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

# Git exits with 128 for a path that does not exist at the ref, and for every other fatal error.
# ``changed_test_functions`` runs ``touched_paths`` first, which raises for an unknown ref.
_GIT_FATAL = 128


@dataclass(frozen=True, order=True)
class FunctionChange:
    """A test function that the head of a pull request adds, deletes, or changes."""

    path: str
    qualname: str
    kind: str

    @property
    def node_id(self) -> str:
        """Return the pytest node id, which joins the parts of the qualified name with ``::``."""
        return f"{self.path}::{self.qualname.replace('.', '::')}"


def collectable_tests(tree: ast.Module) -> dict[str, _FunctionNode]:
    """Return the test functions that pytest collects from ``tree``, keyed by qualified name.

    The rules come from ``pytest.ini``. A module-level function collects when its name starts with
    ``test_``. A method with that prefix collects when its class name starts with ``Test``, and so
    does a method of a ``Test`` class nested in a ``Test`` class. A function defined inside a test
    does not collect.

    Ceiling: the walk reads the body of the module and of each ``Test`` class, so it misses a test
    defined under an ``if`` or ``try``. To lift the ceiling, descend into compound statements.
    """
    return dict(_walk_tests(tree, ()))


def _walk_tests(node: ast.Module | ast.ClassDef, scope: tuple[str, ...]) -> Iterator[tuple[str, _FunctionNode]]:
    for child in node.body:
        if isinstance(child, _FunctionNode) and child.name.startswith("test_"):
            yield ".".join((*scope, child.name)), child
        elif isinstance(child, ast.ClassDef) and child.name.startswith("Test"):
            yield from _walk_tests(child, (*scope, child.name))


def function_fingerprints(source: str, path: str) -> dict[str, str]:
    """Return the fingerprint of each collectable test in ``source``, keyed by qualified name.

    A syntax error in ``source`` raises with ``path`` in its message.
    """
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as err:
        # ``str(err)`` shows only the base name of the file, so the message needs the whole path.
        err.msg = f"{path}: {err.msg}"
        raise
    return {qualname: function_fingerprint(fn) for qualname, fn in collectable_tests(tree).items()}


def diff_functions(base_source: str | None, head_source: str | None, path: str) -> list[FunctionChange]:
    """Return the tests that ``head_source`` adds, deletes, or changes relative to ``base_source``.

    ``None`` means that the file does not exist on that side. The result is sorted by qualified name.
    """
    base = {} if base_source is None else function_fingerprints(base_source, path)
    head = {} if head_source is None else function_fingerprints(head_source, path)
    changed = {name for name in base.keys() & head.keys() if base[name] != head[name]}
    by_kind = ((ADDED, head.keys() - base.keys()), (DELETED, base.keys() - head.keys()), (CHANGED, changed))
    return sorted(FunctionChange(path, name, kind) for kind, names in by_kind for name in names)


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True)


def git_show(repo_root: Path, ref: str, path: str) -> str | None:
    """Return the text of ``path`` at ``ref``, or ``None`` when git exits with 128.

    Git does that for a path that does not exist at ``ref`` and for a ``ref`` it does not know. Any other
    git failure raises ``subprocess.CalledProcessError``.
    """
    result = _run_git(repo_root, "show", f"{ref}:{path}")
    if result.returncode == _GIT_FATAL:
        return None
    result.check_returncode()
    return result.stdout


def touched_paths(repo_root: Path, base: str, roots: Sequence[str]) -> list[str]:
    """Return the paths under ``roots`` that ``HEAD`` adds, modifies, or deletes relative to ``base``.

    ``--no-renames`` lists a rename as a deletion of the source path and an addition of the target path.
    """
    # Ceiling: git quotes a path with unusual characters in this output, and test modules here have
    # plain names. To lift it, add ``-z`` and split the output on NUL. A second ceiling: git does not
    # quote a path with a space, but the ``_pytest`` action splits its ``paths`` input on spaces, so
    # pytest exits 4 on the two halves and the verdict reads ``error``. No test path in this repository
    # has a space.
    result = _run_git(repo_root, "diff", "--name-only", "--no-renames", "--diff-filter=AMD", base, "HEAD", "--", *roots)
    result.check_returncode()
    return sorted(result.stdout.splitlines())


def is_test_module(path: str) -> bool:
    """Return whether the base name of ``path`` matches the ``python_files`` rule of ``pytest.ini``."""
    return PurePosixPath(path).match("test_*.py")


def changed_test_functions(
    repo_root: Path, base: str, roots: Sequence[str] = ("tests",)
) -> tuple[list[str], list[FunctionChange]]:
    """Return the paths that ``HEAD`` touches under ``roots`` and the test functions that changed in them.

    A path that does not exist at ``base`` or at ``HEAD`` reads as an empty file on that side.
    """
    touched = touched_paths(repo_root, base, roots)
    changes: list[FunctionChange] = []
    for path in filter(is_test_module, touched):
        changes += diff_functions(git_show(repo_root, base, path), git_show(repo_root, "HEAD", path), path)
    return touched, sorted(changes)
