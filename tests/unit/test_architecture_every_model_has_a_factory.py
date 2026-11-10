"""Guard: every ORM model has a ``SQLAlchemyModelFactory`` in ``tests/factories/``.

A test seeds a row through a factory, and the harness binds a session to each factory registered in
``ALL_FACTORIES``. A model with no factory leaves the test one way to create the row: construct the
model by hand and call ``session.add()``. ``test_architecture_repository_pattern.py`` bans that call in
test bodies. The missing factory is the defect, and the ``session.add()`` is its symptom.

The scan collects the class name of every ORM model in ``src/core/database/models.py``. It reads the AST
of each module directly under ``tests/factories/``. A class is a factory when it derives from
``SQLAlchemyModelFactory``, written bare or as an attribute (``factory.alchemy.SQLAlchemyModelFactory``).
Its nested ``Meta`` class assigns ``model = Tenant`` or ``model = models.Tenant``, and the scan credits
that model. A Pydantic factory (``factory.Factory``) named after a model builds a schema object, not a
row, and does not count. The scan reads class definitions and does not read ``ALL_FACTORIES``. A row is
the model's class name in a one-tuple.

``KNOWN_MODELS_WITHOUT_FACTORY`` lists the models that had no factory when this guard landed (#2537).
It only shrinks, and every row carries ``# FIXME(#2537)``. A model gets its factory in the change that
declares it and adds no row.

To leave the list, add the factory in ``tests/factories/`` and add it to ``ALL_FACTORIES`` in
``tests/factories/__init__.py``. Delete the model's row in the same change. The row is stale as soon as
the factory exists, and the stale-entry check fails until the row is deleted.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

import pytest

from tests.unit._architecture_helpers import (
    REPO_ROOT,
    assert_detector_catches_ast_snippets,
    assert_detector_ignores_ast_snippets,
    assert_violations_match_allowlist,
    orm_model_class_defs,
    safe_parse,
    trailing_name,
)

#: The one factory base that builds database rows. ``factory.Factory`` and ``factory.DictFactory`` build
#: Pydantic and plain objects, so a class that derives from them credits no model.
_ORM_FACTORY_BASE = "SQLAlchemyModelFactory"

#: The scan reads the modules directly under this directory and not its subdirectories.
_FACTORIES_DIR = REPO_ROOT / "tests" / "factories"

#: Class names of the ORM models that had no ``SQLAlchemyModelFactory`` when this guard landed. SHRINK-ONLY:
#: once a model gains a factory, the stale-entry check fails until its row is deleted. Each row is an open
#: gap tracked by #2537.
KNOWN_MODELS_WITHOUT_FACTORY: frozenset[tuple[str]] = frozenset(
    {
        ("AuditLog",),  # FIXME(#2537)
        ("CreativeReview",),  # FIXME(#2537)
        ("GAMLineItem",),  # FIXME(#2537)
        ("GAMOrder",),  # FIXME(#2537)
        ("IdempotencyAttempt",),  # FIXME(#2537)
        ("ObjectWorkflowMapping",),  # FIXME(#2537)
        ("ProductInventoryMapping",),  # FIXME(#2537)
        ("ReplayNonce",),  # FIXME(#2537)
        ("Strategy",),  # FIXME(#2537)
        ("StrategyState",),  # FIXME(#2537)
        ("SyncJob",),  # FIXME(#2537)
        ("TenantManagementConfig",),  # FIXME(#2537)
        ("WebhookDeliveryLog",),  # FIXME(#2537)
        ("WebhookDeliveryRecord",),  # FIXME(#2537)
    }
)


def _meta_model_names(factory: ast.ClassDef) -> list[str | None]:
    """The name in each ``model = X`` of the nested ``Meta`` class of *factory*, ``None`` where ``X`` is no name."""
    metas = [member for member in factory.body if isinstance(member, ast.ClassDef) and member.name == "Meta"]
    return [
        trailing_name(stmt.value)
        for meta in metas
        for stmt in meta.body
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "model" for t in stmt.targets)
    ]


def factory_model_names(tree: ast.Module) -> set[str]:
    """Class names of the ORM models that a ``SQLAlchemyModelFactory`` in *tree* builds.

    A class at any depth counts when one of its bases is ``SQLAlchemyModelFactory`` or
    ``<module>.SQLAlchemyModelFactory``, and its ``Meta`` assigns ``model = X`` or ``model = <module>.X``.
    A ``model`` value that is neither of those, a call for example, credits nothing.

    Ceiling: the scan does not follow a base chain, so a factory that derives from another factory class
    credits no model. If an abstract ORM factory base appears, walk the chain with ``class_base_index``.
    """
    return {
        name
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and any(trailing_name(base) == _ORM_FACTORY_BASE for base in cls.bases)
        for name in _meta_model_names(cls)
        if name is not None
    }


def find_missing_factories(models: set[str], factory_trees: Iterable[ast.Module]) -> list[str]:
    """The names in *models* that no ``SQLAlchemyModelFactory`` in *factory_trees* builds, sorted."""
    built = {name for tree in factory_trees for name in factory_model_names(tree)}
    return sorted(models - built)


def _factory_trees() -> list[ast.Module]:
    """The parsed modules directly under ``tests/factories/``, in path order. An unparseable file is skipped."""
    parsed = (safe_parse(path) for path in sorted(_FACTORIES_DIR.glob("*.py")))
    return [tree for tree in parsed if tree is not None]


def scan() -> set[tuple[str]]:
    """``(model name,)`` for each ORM model in ``models.py`` that no module under ``tests/factories/`` builds."""
    models = {cls.name for cls in orm_model_class_defs()}
    return {(name,) for name in find_missing_factories(models, _factory_trees())}


def _missing_tenant(tree: ast.Module) -> list[int]:
    return [1] if find_missing_factories({"Tenant"}, [tree]) else []


def test_flags_a_model_with_no_orm_factory():
    assert_detector_catches_ast_snippets(
        _missing_tenant,
        snippets={
            "other model only": "class UserFactory(factory.alchemy.SQLAlchemyModelFactory):\n    class Meta:\n        model = User\n",
            "pydantic factory named like the model": "class TenantFactory(factory.Factory):\n    class Meta:\n        model = Tenant\n",
        },
    )


def test_credits_bare_and_attribute_model_names():
    assert_detector_ignores_ast_snippets(
        _missing_tenant,
        snippets={
            "bare": "class TenantFactory(factory.alchemy.SQLAlchemyModelFactory):\n    class Meta:\n        model = Tenant\n",
            "attribute": "class TenantFactory(SQLAlchemyModelFactory):\n    class Meta:\n        model = models.Tenant\n",
            "inside a function body": "def build():\n    class TenantFactory(factory.alchemy.SQLAlchemyModelFactory):\n        class Meta:\n            model = Tenant\n",
        },
    )


@pytest.mark.arch_guard
def test_every_orm_model_has_a_factory():
    assert_violations_match_allowlist(
        scan(),
        set(KNOWN_MODELS_WITHOUT_FACTORY),
        fix_hint="add a SQLAlchemyModelFactory in tests/factories/ and register it in ALL_FACTORIES",
    )
