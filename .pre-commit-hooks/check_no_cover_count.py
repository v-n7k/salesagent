#!/usr/bin/env python3
"""
Counts the `# pragma: no cover` comments under src/ and fails when the count rises.

The baseline lives in .no-cover-baseline at the repository root. The shared count_ratchet driver does the rest:
it creates, compares and lowers the baseline, and checks it against upstream.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from count_ratchet import (
    count_regex_in_sources,
    int_baseline_io,
    parse_ratchet_args,
    resolve_ratchet_paths,
    run_count_ratchet,
)

BASELINE_FILE = ".no-cover-baseline"
SRC_DIR = "src"
KEY = "no_cover"
KEYS = (KEY,)
# Coverage's own pragma pattern (coverage.config.DEFAULT_EXCLUDE[0]); pyproject adds no other pragma spelling.
# Text match, as coverage's exclusion is: a string holding the comment counts here and is excluded there alike.
NO_COVER = re.compile(r"#\s*(?:pragma|PRAGMA)[:\s]?\s*(?:no|NO)\s*(?:cover|COVER)")


def count_no_cover(src_path: Path) -> int:
    """Count all # pragma: no cover comments in Python files within src/."""
    return count_regex_in_sources(src_path, NO_COVER)


def main() -> int:
    args = parse_ratchet_args("Check that # pragma: no cover count doesn't increase")
    repo_root, src_path, baseline_file = resolve_ratchet_paths(baseline_name=BASELINE_FILE)
    read_baseline, write_baseline = int_baseline_io(KEY)

    return run_count_ratchet(
        keys=KEYS,
        current={KEY: count_no_cover(src_path)},
        baseline_file=baseline_file,
        update_baseline=args.update_baseline,
        repo_root=repo_root,
        parse_upstream=lambda text: {KEY: int(text.strip())},
        count_upstream=lambda tree: {KEY: count_no_cover(tree / SRC_DIR)},
        read_baseline=read_baseline,
        write_baseline=write_baseline,
        increase_header="pragma: no cover count increased!",
        increase_hints=(
            "Cover the line with a test instead of excluding it.",
            "A line that cannot run in any suite is a design question for the PR, not a pragma.",
        ),
        format_key=lambda _key: "pragma: no cover",
    )


if __name__ == "__main__":
    sys.exit(main())
