"""Tests for the AST normalizer shared by the clone index and the red-on-base gate."""

from __future__ import annotations

import ast

from scripts.ci.ast_normalize import (
    dump_statements,
    function_fingerprint,
    iter_functions,
    local_bindings,
    normalize_function,
    strip_docstring,
)

parse = ast.parse


def fn(src: str) -> ast.FunctionDef:
    """Return the first function defined in ``src``."""
    node = parse(src).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def test_iter_functions_yields_qualnames_at_every_depth() -> None:
    tree = parse(
        "def a():\n    def b():\n        pass\nclass C:\n    def m(self):\n        pass\n    class D:\n        def n(self):\n            pass\n"
    )
    assert [q for q, _ in iter_functions(tree)] == ["a", "a.b", "C.m", "C.D.n"]


def test_local_bindings_are_ordered_and_deduplicated() -> None:
    f = fn(
        "def f(a, *rest, k=1, **kw):\n    x = a\n    for i in rest:\n        x += i\n    try:\n        pass\n    except KeyError as err:\n        x = err\n    import os as _os\n    def inner():\n        y = 1\n    return x\n"
    )
    assert local_bindings(f) == ["a", "rest", "k", "kw", "x", "i", "err", "_os", "inner"]


def test_normalize_function_renames_locals_and_types_constants() -> None:
    f = fn('def f(tenant):\n    """doc"""\n    row = repo.get(tenant, limit=10, label="x")\n    return row\n')
    assert dump_statements(normalize_function(f)) == dump_statements(
        strip_docstring(fn("def f(_v0):\n    _v1 = repo.get(_v0, limit=INT, label=STR)\n    return _v1\n").body)
    )


def test_normalize_function_keeps_none_and_bools_and_free_names() -> None:
    f = fn("def f():\n    x = helper(None, True, False)\n    return x\n")
    dumped = dump_statements(normalize_function(f))
    assert "Name('None'" not in dumped
    assert "Constant(None)" in dumped
    # ``bool`` is a subclass of ``int``, so a check that tests for ``int`` first would turn these into ``BOOL``.
    assert "Constant(True)" in dumped and "Constant(False)" in dumped
    assert "Name('BOOL'" not in dumped
    assert "Name('helper'" in dumped


def test_normalize_function_leaves_the_tree_untouched() -> None:
    f = fn("def f(a):\n    b = a\n    return b\n")
    normalize_function(f)
    assert f.body[0].targets[0].id == "b"


def test_fingerprint_ignores_names_docstrings_and_literal_values() -> None:
    a = fn('def test_one():\n    """a"""\n    x = make(1)\n    assert x == "a"\n')
    b = fn('def test_two():\n    """b"""\n    y = make(2)\n    assert y == "b"\n')
    assert function_fingerprint(a) == function_fingerprint(b)


def test_fingerprint_sees_decorators_parameters_and_body() -> None:
    base = fn("def t(a):\n    assert a\n")
    assert function_fingerprint(fn("@pytest.mark.x\ndef t(a):\n    assert a\n")) != function_fingerprint(base)
    assert function_fingerprint(fn("def t(a, b):\n    assert a\n")) != function_fingerprint(base)
    assert function_fingerprint(fn("def t(a):\n    assert not a\n")) != function_fingerprint(base)


def test_fingerprint_ignores_parameter_names_but_sees_annotations() -> None:
    base = fn("def t(tenant: Tenant):\n    return tenant\n")
    assert function_fingerprint(fn("def t(other: Tenant):\n    return other\n")) == function_fingerprint(base)
    assert function_fingerprint(fn("def t(tenant: Account):\n    return tenant\n")) != function_fingerprint(base)


def test_fingerprint_ignores_a_docstring_that_only_one_function_has() -> None:
    documented = fn('def t():\n    """doc"""\n    assert True\n')
    assert function_fingerprint(documented) == function_fingerprint(fn("def t():\n    assert True\n"))


def test_normalize_function_keeps_every_singleton_constant() -> None:
    f = fn("def f():\n    return (None, True, False, ...)\n")
    assert dump_statements(normalize_function(f)) == dump_statements(f.body)


def test_function_fingerprint_leaves_the_tree_untouched() -> None:
    f = fn('def f(a):\n    """doc"""\n    b = a\n    return b\n')
    before = ast.dump(f)
    function_fingerprint(f)
    assert ast.dump(f) == before


def test_fingerprint_ignores_the_spelling_of_declared_names() -> None:
    handler = fn("def t():\n    try:\n        pass\n    except KeyError as e:\n        h(e)\n")
    renamed_handler = fn("def t():\n    try:\n        pass\n    except KeyError as exc:\n        h(exc)\n")
    assert function_fingerprint(handler) == function_fingerprint(renamed_handler)
    alias = fn("def t():\n    import os as a\n    return a.sep\n")
    renamed_alias = fn("def t():\n    import os as b\n    return b.sep\n")
    assert function_fingerprint(alias) == function_fingerprint(renamed_alias)
    helper = fn("def t():\n    def helper():\n        pass\n    helper()\n")
    renamed_helper = fn("def t():\n    def _helper():\n        pass\n    _helper()\n")
    assert function_fingerprint(helper) == function_fingerprint(renamed_helper)
    async_helper = fn("def t():\n    async def helper():\n        pass\n    helper()\n")
    renamed_async_helper = fn("def t():\n    async def _helper():\n        pass\n    _helper()\n")
    assert function_fingerprint(async_helper) == function_fingerprint(renamed_async_helper)
    scopes = fn("def t():\n    class Fake:\n        pass\n    async def run():\n        pass\n    return Fake, run\n")
    renamed_scopes = fn(
        "def t():\n    class _Fake:\n        pass\n    async def _run():\n        pass\n    return _Fake, _run\n"
    )
    assert function_fingerprint(scopes) == function_fingerprint(renamed_scopes)
