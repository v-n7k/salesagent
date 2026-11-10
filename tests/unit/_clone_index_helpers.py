"""Fixture sources for the clone index tests and the clone-count hook tests.

``SEED_A`` and ``SEED_B`` are the same five statements with other local names and other literal
values, so they share one normalized window. Each source starts without a blank line, so its
``def`` is on line 1. ``SEED_PAIR`` holds the two functions that are clone-bearing when ``SEED_A``
is written as ``src/a.py`` and ``SEED_B`` as ``tests/b.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from scripts.ci.clone_index import FunctionRef

SEED_A = """\
def seed_tenant(session, name):
    tenant = TenantFactory(name=name)
    session.add(tenant)
    session.flush()
    principal = PrincipalFactory(tenant=tenant, token="abc")
    return principal
"""
SEED_B = """\
def seed_other(db, label):
    row = TenantFactory(name=label)
    db.add(row)
    db.flush()
    who = PrincipalFactory(tenant=row, token="xyz")
    return who
"""
# SEED_B with `db.flush()` changed to `db.commit()`. It is written out because the import-time
# filesystem guard reads a module-level `.replace(...)` call as `Path.replace`.
SEED_B_OTHER_CALL = """\
def seed_other(db, label):
    row = TenantFactory(name=label)
    db.add(row)
    db.commit()
    who = PrincipalFactory(tenant=row, token="xyz")
    return who
"""
SEED_PAIR = frozenset({FunctionRef("src/a.py", "seed_tenant", 1), FunctionRef("tests/b.py", "seed_other", 1)})


def write_sources(root: Path, files: Mapping[str, str]) -> None:
    """Write each ``files[relative_path]`` under ``root``, creating the directories it needs."""
    for relative_path, source in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
