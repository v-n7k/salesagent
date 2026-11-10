"""Normalize Python functions so that two functions with the same shape compare equal.

The clone index and the red-on-base gate share this module. Both need one answer to the
question "are these two test functions the same?". The answer ignores names, docstrings, and
literal values. It counts structure: decorators, parameters, defaults, annotations, and the body.

A name that a function binds, such as a parameter, an assignment target, or a loop variable,
becomes ``_v{index}``, where ``index`` is the position of the name in ``local_bindings``. A
``str``, ``bytes``, ``int``, ``float``, or ``complex`` literal becomes its type name in upper
case (``STR``, ``BYTES``, ``INT``, ``FLOAT``, ``COMPLEX``). ``None``, ``True``, ``False``, and
``...`` stay as written.
"""

from __future__ import annotations

import ast
import copy
import hashlib
from collections.abc import Iterable, Iterator, Sequence

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

# The literal types that `Normalizer` replaces with the name of their type.
_TYPED_LITERALS = (str, bytes, int, float, complex)


def iter_functions(tree: ast.Module) -> Iterator[tuple[str, _FunctionNode]]:
    """Yield each function in ``tree`` at any depth, paired with its qualified name.

    The qualified name joins the enclosing classes and functions with dots. A method of a nested
    class is ``Outer.Inner.method``, and a function inside a function is ``outer.inner``.
    The generator yields in source order, an enclosing function before the functions it contains.
    """
    yield from _walk_scope(tree, ())


def _walk_scope(node: ast.AST, scope: tuple[str, ...]) -> Iterator[tuple[str, _FunctionNode]]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FunctionNode):
            yield ".".join((*scope, child.name)), child
        # The name of a class or function prefixes the qualified name of everything inside it.
        inner = (*scope, child.name) if isinstance(child, _FunctionNode | ast.ClassDef) else scope
        yield from _walk_scope(child, inner)


class _BindingCollector(ast.NodeVisitor):
    """Collect the names a function body binds, without entering a nested scope."""

    def __init__(self, parameters: Iterable[str]) -> None:
        # A dict works as an ordered set: assigning a key a second time keeps its first position.
        self.names: dict[str, None] = dict.fromkeys(parameters)

    def _bind(self, name: str) -> None:
        self.names[name] = None

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self._bind(node.id)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self._bind(node.name)
        self.generic_visit(node)

    def visit_alias(self, node: ast.alias) -> None:
        if node.asname:
            self._bind(node.asname)

    def _bind_nested_scope(self, node: _FunctionNode | ast.ClassDef) -> None:
        self._bind(node.name)

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _bind_nested_scope


def local_bindings(fn: _FunctionNode) -> list[str]:
    """Return the names ``fn`` binds, in order of first appearance and without repeats.

    The parameters come first, in the order positional-only, positional, ``*args``, keyword-only,
    ``**kwargs``. The body then adds each ``Name`` in ``Store`` context, each ``except ... as``
    name, each ``import ... as`` name, and the name of each nested ``def`` or ``class``. The
    function does not enter the body of a nested ``def`` or ``class``, because those names
    belong to that scope.
    """
    args = fn.args
    parameters = (*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg)
    collector = _BindingCollector(p.arg for p in parameters if p is not None)
    for stmt in fn.body:
        collector.visit(stmt)
    return list(collector.names)


class Normalizer(ast.NodeTransformer):
    """Rename the bound names of a function and replace its literal values with their type names.

    A ``Name`` or ``arg`` whose id is in ``bound`` becomes ``_v{index}``, where ``index`` is its
    position in ``bound``. A bound name gets the same rename where it is declared. The declaration
    sites are an ``except ... as`` name, an ``import ... as`` alias, and the name of a ``def`` or
    ``class``. Every other ``Name`` stays, and so do attribute names and keyword argument names.
    A ``str``, ``bytes``, ``int``, ``float``, or ``complex`` constant becomes a ``Name`` that holds
    its type name in upper case. ``None``, ``True``, ``False``, and ``...`` stay.
    The transformer edits the tree in place, so pass it a copy.
    """

    def __init__(self, bound: Sequence[str]) -> None:
        self._index = {name: index for index, name in enumerate(bound)}

    def _rename(self, name: str) -> str:
        index = self._index.get(name)
        return name if index is None else f"_v{index}"

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = self._rename(node.id)
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.arg = self._rename(node.arg)
        self.generic_visit(node)
        return node

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.ExceptHandler:
        if node.name:
            node.name = self._rename(node.name)
        self.generic_visit(node)
        return node

    def visit_alias(self, node: ast.alias) -> ast.alias:
        if node.asname:
            node.asname = self._rename(node.asname)
        return node

    def _rename_declared(self, node: _FunctionNode | ast.ClassDef) -> ast.AST:
        node.name = self._rename(node.name)
        self.generic_visit(node)
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _rename_declared

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        value = node.value
        # `bool` is a subclass of `int`, so test for it first: `True` and `False` stay as written.
        if isinstance(value, bool) or not isinstance(value, _TYPED_LITERALS):
            return node
        return ast.Name(id=type(value).__name__.upper(), ctx=ast.Load())


def strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """Return a copy of ``body`` without a leading string-constant expression statement."""
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return body[1:]
    return list(body)


def normalize_function(fn: _FunctionNode) -> list[ast.stmt]:
    """Return a normalized copy of the statements in ``fn``, without the docstring.

    The copy goes through ``Normalizer(local_bindings(fn))``. The function does not modify ``fn``.
    """
    normalizer = Normalizer(local_bindings(fn))
    return [normalizer.visit(stmt) for stmt in copy.deepcopy(strip_docstring(fn.body))]


def _dump(node: ast.AST) -> str:
    # One place for the dump options, so the statement dump and the fingerprint cannot drift apart.
    return ast.dump(node, annotate_fields=False, include_attributes=False)


def dump_statements(stmts: Iterable[ast.stmt]) -> str:
    """Return the dump of each statement in ``stmts``, one statement per line."""
    return "\n".join(_dump(stmt) for stmt in stmts)


def function_fingerprint(fn: _FunctionNode) -> str:
    """Return the SHA-1 hex digest of the normalized shape of ``fn``.

    The digest covers the whole definition, so decorators, parameters, defaults, annotations, and
    the body all count. The name of the function and its docstring do not. The function does not
    modify ``fn``.
    """
    node = copy.deepcopy(fn)
    node.body = strip_docstring(node.body)
    node.name = ""  # The function's own name must not change the digest.
    normalized = ast.fix_missing_locations(Normalizer(local_bindings(fn)).visit(node))
    return hashlib.sha1(_dump(normalized).encode()).hexdigest()
