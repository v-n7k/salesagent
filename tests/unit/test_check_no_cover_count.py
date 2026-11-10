"""Counter and pins of the `# pragma: no cover` ratchet hook."""

from __future__ import annotations

import re
from pathlib import Path

import coverage

from tests.unit._architecture_helpers import load_hook_module, repo_root

hook = load_hook_module("check_no_cover_count")

#: One line per spelling that coverage excludes a line for.
SPELLINGS = (
    "a = 1  # pragma: no cover",
    "b = 2  #pragma: no cover",
    "c = 3  # pragma:no cover",
    "d = 4  # pragma no cover",
    "e = 5  # pragma: nocover",
    "f = 6  # pragma: no  cover",
    "g = 7  # PRAGMA: NO COVER",
)
NO_BRANCH = "x = 1  # pragma: no branch"


def test_pins() -> None:
    assert hook.BASELINE_FILE == ".no-cover-baseline"
    assert hook.SRC_DIR == "src"
    assert hook.KEYS == ("no_cover",)


def test_count_no_cover_counts_every_spelling(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("\n".join([*SPELLINGS, NO_BRANCH]) + "\n")
    assert hook.count_no_cover(tmp_path) == 7


def test_count_no_cover_needs_the_comment_marker(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text('MESSAGE = "pragma: no cover"\n')
    assert hook.count_no_cover(tmp_path) == 0


def test_no_cover_pattern_agrees_with_the_project_exclusions() -> None:
    """The counter must count exactly the pragma lines this repository's report excludes.

    The structural exclusions (`def __repr__`, `if TYPE_CHECKING:` and the rest) are policy, not per-line
    opt-outs, so the sample holds lines that mention the pragma and one plain line.
    """
    exclusions = coverage.Coverage(config_file=str(repo_root() / "pyproject.toml")).get_option("report:exclude_lines")
    for line in [*SPELLINGS, NO_BRANCH, 'MESSAGE = "pragma: no cover"', "x = 1"]:
        assert bool(hook.NO_COVER.search(line)) == any(re.search(pattern, line) for pattern in exclusions), line
