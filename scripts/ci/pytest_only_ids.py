"""A pytest plugin that runs only the tests whose node ids a file lists.

The red-on-base gate gives pytest the files that hold its changed tests, and ``--only-ids IDS`` names the
file of node ids that ``python -m scripts.ci.redden_on_base ids`` wrote. The plugin deselects every
collected test whose node id, without its parameter set, is not in that file. The file arguments keep a
test module that cannot import on the base from ending the run, which node ids as arguments would do.

Load it with ``-p scripts.ci.pytest_only_ids``. Pytest imports a ``-p`` plugin while it reads the command
line, before it loads any conftest and so before a conftest puts the repository root on ``sys.path``. The
job therefore sets ``PYTHONPATH=.`` for ``scripts`` to resolve. The plugin lives here and not in a conftest
so that the option exists in every run of the job, whichever conftests the checkout holds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci.redden_on_base import function_node_id


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--only-ids",
        default=None,
        help="Run only the tests whose node id, without its parameter set, is listed in this file, one per line.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    ids_file = config.getoption("--only-ids")
    if ids_file is None:
        return
    wanted = {stripped for line in Path(ids_file).read_text().splitlines() if (stripped := line.strip())}
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if function_node_id(item.nodeid) in wanted:
            kept.append(item)
        else:
            deselected.append(item)
    config.hook.pytest_deselected(items=deselected)
    items[:] = kept
