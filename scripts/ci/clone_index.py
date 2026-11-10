"""Index the statement windows of every function, to find functions that copy each other.

A window is a run of ``WINDOW`` consecutive statements in one statement list of a function: its
body, or the body of an ``if``, ``for``, ``while``, ``with``, ``try``, ``except``, ``else``,
``finally`` or ``match`` case inside it, at any depth. A nested ``def`` or ``class`` is one
statement of the enclosing function; its body is not scanned as part of that function, and a
nested function is indexed as a function of its own. With ``REQUIRE_CALL``, a window counts only
if it contains a call, which leaves out runs of plain assignments and assertions.

Windows are compared after ``scripts/ci/ast_normalize.py`` normalizes the function: bound names
become ``_v{n}`` labels and literal values are replaced by their type, so a copy that uses other
names and values has the same shape. The labels are numbered across the whole function, so the
label of a name inside a window depends on the parameter list and on every binding before the
window. The window is the unit that is hashed, so ``relabel_window`` numbers the names again,
positionally in order of first appearance inside the window (``_w0``, ``_w1``, ...). Two copies of
one run of statements then hash the same wherever each sits in its function.

A function is clone-bearing when one of its windows also occurs in another function, in the same
file or in any other file under the scanned roots. The same window twice inside one function does
not count. The clone ratchet (``.pre-commit-hooks/check_clone_count.py``) counts clone-bearing
functions per root.

Only ``index_tree`` reads files. Everything else is a function of its arguments.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.ci.ast_normalize import dump_statements, iter_functions, normalize_function

WINDOW: int = 5
REQUIRE_CALL: bool = True
ROOTS: tuple[str, ...] = ("src", "tests", "scripts", ".pre-commit-hooks", ".claude/scripts")
# A file with one of these as a component of its path relative to the scanned root is not scanned.
SKIP_PARTS: frozenset[str] = frozenset({"__pycache__", "node_modules", ".venv", ".tox", "vendor"})

_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
# A bound-name label in a dump: the normalizer writes `_v{n}`, and `ast.dump` quotes an identifier.
_BOUND_LABEL = re.compile(r"(?<=')_v\d+(?=')")


@dataclass(frozen=True, order=True)
class FunctionRef:
    """A function in the scanned tree.

    ``path`` is the file's posix path relative to the ``root`` that ``index_tree`` scanned, so a
    file under ``.claude/scripts`` keeps that prefix. ``qualname`` joins the enclosing classes and
    functions with dots (``Outer.inner``). ``lineno`` is the line of the ``def``.
    """

    path: str
    qualname: str
    lineno: int


@dataclass(frozen=True)
class Window:
    """One window of ``function``, from its first source line ``start`` to its last, ``end``."""

    function: FunctionRef
    start: int
    end: int


def statement_lists(stmts: list[ast.stmt]) -> Iterator[list[ast.stmt]]:
    """Yield ``stmts`` and every non-empty statement list inside it, in source order.

    The generator does not enter the body of a nested ``def`` or ``class``.
    """
    yield stmts
    for stmt in stmts:
        for inner in _inner_statement_lists(stmt):
            if inner:
                yield from statement_lists(inner)


def _inner_statement_lists(stmt: ast.stmt) -> Iterator[list[ast.stmt]]:
    """Yield the statement lists directly inside ``stmt``, in source order."""
    if isinstance(stmt, _NESTED_SCOPES):
        return
    yield getattr(stmt, "body", [])
    for handler in getattr(stmt, "handlers", []):
        yield handler.body
    yield getattr(stmt, "orelse", [])
    yield getattr(stmt, "finalbody", [])
    for case in getattr(stmt, "cases", []):
        yield case.body


def _has_call(stmts: list[ast.stmt]) -> bool:
    return any(isinstance(node, ast.Call) for stmt in stmts for node in ast.walk(stmt))


def relabel_window(dump: str) -> str:
    """Return ``dump`` with each ``_v{n}`` label renumbered ``_w0``, ``_w1``, ... by first appearance."""
    labels: dict[str, str] = {}
    return _BOUND_LABEL.sub(lambda match: labels.setdefault(match.group(), f"_w{len(labels)}"), dump)


def function_windows(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, *, window: int = WINDOW, require_call: bool = REQUIRE_CALL
) -> dict[str, tuple[int, int]]:
    """Map the hash of each distinct window of ``fn`` to the first and last line of its first occurrence.

    The hash is the SHA-1 hex digest of ``relabel_window`` applied to ``dump_statements`` of the
    window's normalized statements.
    """
    windows: dict[str, tuple[int, int]] = {}
    for stmts in statement_lists(normalize_function(fn)):
        for offset in range(len(stmts) - window + 1):
            run = stmts[offset : offset + window]
            if require_call and not _has_call(run):
                continue
            digest = hashlib.sha1(relabel_window(dump_statements(run)).encode()).hexdigest()
            windows.setdefault(digest, (run[0].lineno, run[-1].end_lineno or run[-1].lineno))
    return windows


# Deliberate simplification: there is no per-file cache, so every call parses and normalizes the
# whole tree, about 13 to 18 s for the five roots (some 1,700 files). The upgrade path is a cache
# keyed by path and mtime, like `tests/unit/_architecture_helpers.parse_module`.
def index_tree(
    root: Path, roots: Sequence[str] = ROOTS, *, window: int = WINDOW, require_call: bool = REQUIRE_CALL
) -> dict[str, list[Window]]:
    """Map each window hash to its windows in every ``.py`` file under ``root / r`` for each ``r`` in ``roots``.

    Files are indexed in sorted path order. A root that does not exist adds nothing, and a file
    with a ``SKIP_PARTS`` component in its path is not scanned. A file that does not parse raises
    ``SyntaxError`` with its path in the message.
    """
    index: dict[str, list[Window]] = {}
    for path in _scanned_files(root, roots):
        rel_path = path.relative_to(root).as_posix()
        for qualname, fn in iter_functions(_parse(path, rel_path)):
            ref = FunctionRef(rel_path, qualname, fn.lineno)
            _index_function(index, ref, fn, window=window, require_call=require_call)
    return index


def _scanned_files(root: Path, roots: Sequence[str]) -> list[Path]:
    found = {
        path
        for name in roots
        if (root / name).is_dir()
        for path in (root / name).rglob("*.py")
        if SKIP_PARTS.isdisjoint(path.relative_to(root).parts)
    }
    return sorted(found)


def _parse(path: Path, rel_path: str) -> ast.Module:
    try:
        return ast.parse(path.read_bytes(), filename=rel_path)
    except SyntaxError as exc:
        # str() of a SyntaxError shows only the base name of the file, so the message carries the path.
        raise SyntaxError(f"{rel_path}: {exc}") from exc


def _index_function(
    index: dict[str, list[Window]],
    ref: FunctionRef,
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    window: int,
    require_call: bool,
) -> None:
    for digest, (start, end) in function_windows(fn, window=window, require_call=require_call).items():
        index.setdefault(digest, []).append(Window(ref, start, end))


def _neighbours(index: Mapping[str, list[Window]]) -> dict[FunctionRef, set[FunctionRef]]:
    """Map each clone-bearing function to the other functions that share a window with it."""
    neighbours: dict[FunctionRef, set[FunctionRef]] = {}
    for windows in index.values():
        functions = {w.function for w in windows}
        if len(functions) > 1:
            for fn in functions:
                neighbours.setdefault(fn, set()).update(functions - {fn})
    return neighbours


def clone_bearing_functions(index: Mapping[str, list[Window]]) -> set[FunctionRef]:
    """Return the functions that share at least one window with another function."""
    return set(_neighbours(index))


def clone_partners(index: Mapping[str, list[Window]]) -> dict[FunctionRef, FunctionRef]:
    """Map each clone-bearing function to the smallest other function that shares a window with it."""
    return {fn: min(others) for fn, others in _neighbours(index).items()}


def clone_groups(index: Mapping[str, list[Window]]) -> list[frozenset[FunctionRef]]:
    """Return the connected groups of functions linked by shared windows, sorted by smallest member."""
    neighbours = _neighbours(index)
    groups: list[frozenset[FunctionRef]] = []
    grouped: set[FunctionRef] = set()
    # In sorted order, each new group starts at its smallest member, so the groups come out sorted.
    for fn in sorted(neighbours):
        if fn not in grouped:
            group = _connected(fn, neighbours)
            grouped |= group
            groups.append(frozenset(group))
    return groups


def _connected(start: FunctionRef, neighbours: Mapping[FunctionRef, set[FunctionRef]]) -> set[FunctionRef]:
    """Return ``start`` and every function reachable from it through ``neighbours``."""
    group = {start}
    stack = [start]
    while stack:
        for other in neighbours[stack.pop()] - group:
            group.add(other)
            stack.append(other)
    return group


def new_clone_pairs(
    head: Mapping[str, list[Window]], base: Mapping[str, list[Window]]
) -> list[tuple[FunctionRef, FunctionRef]]:
    """Return each function clone-bearing in ``head`` and not in ``base``, with its partner in ``head``, sorted.

    A function is the same function in both trees when its path and qualname match, so a function
    that only moved to another line is not new. Each pair carries the ``FunctionRef`` from ``head``.
    """
    before = {(fn.path, fn.qualname) for fn in clone_bearing_functions(base)}
    return sorted((fn, partner) for fn, partner in clone_partners(head).items() if (fn.path, fn.qualname) not in before)


def count_by_root(functions: Iterable[FunctionRef], roots: Sequence[str] = ROOTS) -> dict[str, int]:
    """Count ``functions`` under each root, with every root present and ``0`` for a root with none.

    A function counts under the longest root its path starts with, so a nested root takes its own
    files. A path under none of the roots raises ``ValueError``; an index built over the same
    roots holds no such path.
    """
    counts = dict.fromkeys(roots, 0)
    for fn in functions:
        counts[max((root for root in roots if fn.path.startswith(f"{root}/")), key=len)] += 1
    return counts
