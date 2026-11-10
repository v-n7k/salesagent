"""Guard: a class that derives from a harness env is defined under ``tests/harness/`` and nowhere else.

A test module that subclasses ``IntegrationEnv``, ``BaseTestEnv`` or any class that reaches
one defines a private env: its own ``EXTERNAL_PATCHES``, seeding or dispatch. The harness is
what changes when a test cannot express the state it needs (``tests/harness/CLAUDE.md``). A
private subclass leaves that change undone: the missing method stays in the test module, and
the next test that needs the same state copies the subclass.

A module outside ``tests/harness/`` that needs more from an env adds a method to that env, or
uses ``BareIntegrationEnv`` (the repository-level env, with no patches) or the domain env.

The scan indexes every class under ``tests/`` by name, harness included, and reports the ones
outside ``tests/harness/``. A class is found when it reaches an env root through a mixin or
through a harness env, and when it is defined inside a test function. The scan reads the AST,
so a class written inside a string literal is not a class. Rows are keyed
``(path, class name)``, because a line number goes stale on any edit above the class.

``KNOWN_PRIVATE_ENV_SUBCLASSES`` lists the classes outside ``tests/harness/`` that existed
when this guard landed (#2535). It only shrinks, and every row carries ``# FIXME(#2535)``.
Give a new test the env it needs instead of adding a row for it.

To leave the list, delete the subclass from the test module and delete its row in the same
change. Use ``BareIntegrationEnv`` or the domain env, and add any method the test needs to that
env in ``tests/harness/``. The row is stale as soon as the class is gone, and the stale-entry
check fails until the row is deleted.
"""

from __future__ import annotations

import ast

import pytest

from tests.unit._architecture_helpers import (
    assert_detector_catches_ast_snippets,
    assert_detector_ignores_ast_snippets,
    assert_violations_match_allowlist,
    class_base_index,
    env_class_defs,
    iter_test_module_trees,
)

#: Env subclasses may be defined under this prefix, and only under it.
_HARNESS_DIR = "tests/harness/"

#: ``(repo-relative path, class name)`` of each env subclass defined outside ``tests/harness/``
#: when this guard landed. SHRINK-ONLY: once a class is gone, the stale-entry check fails until
#: its row is deleted. Each row is an open gap tracked by #2535.
KNOWN_PRIVATE_ENV_SUBCLASSES: frozenset[tuple[str, str]] = frozenset(
    {
        ("tests/integration/test_account_model.py", "_AccountEnv"),  # FIXME(#2535)
        ("tests/integration/test_account_repository.py", "_RepoEnv"),  # FIXME(#2535)
        ("tests/integration/test_account_resolution_error_codes.py", "_AccountResolutionEnv"),  # FIXME(#2535)
        ("tests/integration/test_account_typed_columns.py", "_AccountEnv"),  # FIXME(#2535)
        ("tests/integration/test_creative_repository.py", "_RepoEnv"),  # FIXME(#2535)
        ("tests/integration/test_decryption_failure_raises.py", "_BareEnv"),  # FIXME(#2535)
        ("tests/integration/test_get_task_principal_scope.py", "_CompleteTaskEnv"),  # FIXME(#2535)
        ("tests/integration/test_get_task_principal_scope.py", "_GetTaskEnv"),  # FIXME(#2535)
        ("tests/integration/test_harness_rest_refusal.py", "_RefusalDialectEnv"),  # FIXME(#2535)
        ("tests/integration/test_harness_signed_dispatch.py", "_SignedDispatchEnv"),  # FIXME(#2535)
        ("tests/integration/test_list_accounts.py", "_AccountListEnv"),  # FIXME(#2535)
        ("tests/integration/test_mock_adapter_format_persistence.py", "_BareEnv"),  # FIXME(#2535)
        ("tests/integration/test_tenant_config_repository.py", "_RepoEnv"),  # FIXME(#2535)
        ("tests/integration/test_tenant_lookup_repository.py", "_RepoEnv"),  # FIXME(#2535)
        ("tests/integration/test_vendor_egress.py", "_BareEnv"),  # FIXME(#2535)
        ("tests/integration/test_virtual_host_integration.py", "_VhostEnv"),  # FIXME(#2535)
    }
)


def find_private_env_subclasses(tree: ast.Module, index: dict[str, set[str]]) -> list[int]:
    """Line numbers of the classes in *tree* that derive from a harness env root."""
    return sorted(node.lineno for node in env_class_defs(tree, index))


def scan() -> set[tuple[str, str]]:
    """``(path, class name)`` for each env subclass defined outside ``tests/harness/``.

    The index is built over every module, harness included, so a class that derives from a
    harness env is found through it. Only the report leaves out ``tests/harness/``.
    """
    modules = iter_test_module_trees()
    index = class_base_index(modules)
    return {
        (path, node.name)
        for path, tree in modules
        if not path.startswith(_HARNESS_DIR)
        for node in env_class_defs(tree, index)
    }


#: Stand-in for the harness class a snippet derives from but cannot define: ``TaskManagementEnv``
#: (tests/harness/task_management.py) derives from the root ``IntegrationEnv``, so a snippet class
#: built on it reaches a root only through a second hop.
_INDEX = {"TaskManagementEnv": {"IntegrationEnv"}}


def _detect(tree: ast.Module) -> list[int]:
    """The detector the snippet tests drive: the snippet's own classes over the harness stand-ins."""
    return find_private_env_subclasses(tree, _INDEX | class_base_index([("x", tree)]))


def test_flags_a_subclass_at_module_level_and_inside_a_function():
    assert_detector_catches_ast_snippets(
        _detect,
        snippets={
            "module level": "class _RepoEnv(IntegrationEnv):\n    EXTERNAL_PATCHES = {}\n",
            "inside a test": "def test_x():\n    class _E(IntegrationEnv):\n        pass\n",
            "mixin beside a root": "class _M:\n    pass\nclass _E(_M, BareIntegrationEnv):\n    pass\n",
            "through a harness env": "class _GetTaskEnv(TaskManagementEnv):\n    pass\n",
        },
    )


def test_ignores_classes_that_do_not_derive_from_an_env_root():
    assert_detector_ignores_ast_snippets(
        _detect,
        snippets={
            "e2e shim": "class _ExistingIdentityEnv(_LiveDBEnv):\n    pass\n",
            "plain class": "class AdminAccountEnv:\n    pass\n",
            "string literal": "_SNIPPET = 'class ProductEnv(IntegrationEnv): pass'\n",
        },
    )


@pytest.mark.arch_guard
def test_no_env_subclass_outside_the_harness():
    assert_violations_match_allowlist(
        scan(),
        set(KNOWN_PRIVATE_ENV_SUBCLASSES),
        fix_hint=(
            "use BareIntegrationEnv or the domain env from tests/harness; "
            "add a method to the env instead of subclassing it in a test module"
        ),
    )
