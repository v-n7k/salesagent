#!/usr/bin/env python3
"""
Quality-ci hook: ratchet the number of clone-bearing functions.

A function is clone-bearing when five consecutive statements of it, with a call among them, also
occur in another function, in the same file or in any other file under the scanned roots. Local
names and literal values are normalized first, so a copy with other variable names or other
constants still matches; ``scripts/ci/clone_index.py`` defines the window and does the counting.
CLAUDE.md treats duplicated logic as a defect, and this ratchet keeps the number of functions that
carry a copy from growing, beside the pylint R0801 ratchet in ``check_code_duplication.py``.

- Track the clone-bearing function count per root: ``src``, ``tests``, ``scripts``,
  ``.pre-commit-hooks`` and ``.claude/scripts``
- Fail only when a count increases (a new copy), and list each new clone-bearing function with
  one partner
- Auto-lower the baseline when a count decreases
- Compares each baseline key against the baseline committed at the merge base and at origin/main;
  a key neither carries yet is graded against ``count_clone_bearing`` run on the upstream tree

Uses shared ``count_ratchet`` for the skeleton and JSON codec, mirroring
check_admin_raw_session_count.py.
"""

from __future__ import annotations

import sys
import tarfile
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from count_ratchet import (
    json_baseline_io,
    materialize_upstream_tree,
    parse_ratchet_args,
    resolve_ratchet_paths,
    run_count_ratchet,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ci.clone_index import (
    ROOTS,
    WINDOW,
    FunctionRef,
    Window,
    clone_bearing_functions,
    count_by_root,
    index_tree,
    new_clone_pairs,
)

BASELINE_FILE = ".clone-baseline"


def count_clone_bearing(repo_root: Path) -> dict[str, int]:
    """Count the clone-bearing functions under each root of ``repo_root``; an absent root counts ``0``."""
    return count_by_root(clone_bearing_functions(index_tree(repo_root)))


def format_new_pairs(pairs: Iterable[tuple[FunctionRef, FunctionRef]]) -> list[str]:
    """Format each ``(new function, partner)`` pair as one line."""
    return [f"  {a.path}:{a.lineno} {a.qualname}  <->  {b.path}:{b.lineno} {b.qualname}" for a, b in pairs]


def hints_for_increase(
    repo_root: Path,
    head: Mapping[str, list[Window]],
    baseline: Mapping[str, int] | None,
    current: Mapping[str, int],
) -> list[str]:
    """Return the lines to print under the increase header, or ``[]`` when no root's count rose.

    A count says that a root rose, not which function is new, and a rise in one root can be hidden
    by a fall in another. So the lines name each function that is clone-bearing in ``head`` and not
    in the upstream tree, with one partner each. Without an upstream ref there is no tree to
    compare with, and the lines are the advice alone. They are the advice alone too when the
    upstream tree cannot be extracted; the failure goes to stderr as a warning, so the per-root
    table still prints.
    """
    if baseline is None or not any(count > baseline.get(root, 0) for root, count in current.items()):
        return []
    hints = [
        "Extract the shared statements into one helper, or route the new copy through the existing one.",
        "",
        "New clone-bearing functions and one partner each:",
    ]
    with tempfile.TemporaryDirectory(prefix="clone-ratchet-upstream-") as tmp:
        try:
            upstream = materialize_upstream_tree(repo_root, ROOTS, Path(tmp))
            if upstream is not None:
                hints += format_new_pairs(new_clone_pairs(head, index_tree(upstream)))
        except (RuntimeError, OSError, tarfile.TarError) as exc:
            print(f"Warning: could not name the new clone pairs: {exc}", file=sys.stderr)
    return hints


def main() -> int:
    args = parse_ratchet_args("Check that the clone-bearing function count does not increase")
    repo_root, _src_path, baseline_file = resolve_ratchet_paths(baseline_name=BASELINE_FILE)
    read_baseline, write_baseline = json_baseline_io(ROOTS)
    print(f"Scanning for clone-bearing functions ({WINDOW}-statement windows)...")
    head = index_tree(repo_root)
    current = count_by_root(clone_bearing_functions(head), ROOTS)
    return run_count_ratchet(
        keys=ROOTS,
        current=current,
        baseline_file=baseline_file,
        update_baseline=args.update_baseline,
        read_baseline=read_baseline,
        write_baseline=write_baseline,
        increase_header="Clone-bearing functions increased! DRY is a non-negotiable invariant.",
        increase_hints=hints_for_increase(repo_root, head, read_baseline(baseline_file), current),
        repo_root=repo_root,
        count_upstream=count_clone_bearing,
        upstream_paths=ROOTS,
        format_key=lambda root: f"{root}/",
        unit="clone-bearing functions",
    )


if __name__ == "__main__":
    sys.exit(main())
