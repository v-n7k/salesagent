"""Tests for the clone index behind the clone ratchet (``scripts/ci/clone_index.py``)."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from scripts.ci.ast_normalize import iter_functions
from scripts.ci.clone_index import (
    REQUIRE_CALL,
    ROOTS,
    WINDOW,
    FunctionRef,
    Window,
    clone_bearing_functions,
    clone_groups,
    clone_partners,
    count_by_root,
    function_windows,
    index_tree,
    new_clone_pairs,
    relabel_window,
    statement_lists,
)
from tests.unit._clone_index_helpers import SEED_A, SEED_B, SEED_B_OTHER_CALL, write_sources


def _write_and_index(root: Path, files: dict[str, str]) -> dict[str, list[Window]]:
    write_sources(root, files)
    return index_tree(root)


def _seed_a_statements(indent: str = "") -> str:
    """Return the five statements of ``SEED_A``, each line indented by ``indent`` more."""
    return textwrap.indent("\n".join(SEED_A.splitlines()[1:]), indent) + "\n"


def test_pins() -> None:
    assert WINDOW == 5
    assert REQUIRE_CALL is True
    assert ROOTS == ("src", "tests", "scripts", ".pre-commit-hooks", ".claude/scripts")


def test_renamed_locals_and_different_literals_are_one_window(tmp_path: Path) -> None:
    index = _write_and_index(tmp_path, {"src/a.py": SEED_A, "tests/b.py": SEED_B})
    assert clone_bearing_functions(index) == {
        FunctionRef("src/a.py", "seed_tenant", 1),
        FunctionRef("tests/b.py", "seed_other", 1),
    }


def test_relabel_window_numbers_labels_by_first_appearance() -> None:
    # The second line names the second label first. `api_v1` and `_v1_x` are not labels.
    dump = (
        "Assign([Name('_v3')], Call(Name('api_v1'), [Name('_v12'), Name('_v1_x')]))\n"
        "Return(Tuple([Name('_v12'), Name('_v3')]))"
    )
    expected = (
        "Assign([Name('_w0')], Call(Name('api_v1'), [Name('_w1'), Name('_v1_x')]))\n"
        "Return(Tuple([Name('_w1'), Name('_w0')]))"
    )
    assert relabel_window(dump) == expected
    assert relabel_window(expected) == expected


@pytest.mark.parametrize(
    ("old", "new"),
    [("(db, label)", "(db, label, unused)"), ("label):\n", "label):\n    scratch = helper()\n")],
    ids=["extra_parameter", "earlier_binding"],
)
def test_a_copy_is_found_whatever_precedes_it_in_its_function(tmp_path: Path, old: str, new: str) -> None:
    index = _write_and_index(tmp_path, {"src/a.py": SEED_A, "tests/b.py": SEED_B.replace(old, new)})
    assert clone_bearing_functions(index) == {
        FunctionRef("src/a.py", "seed_tenant", 1),
        FunctionRef("tests/b.py", "seed_other", 1),
    }


def test_a_different_attribute_name_is_not_a_copy(tmp_path: Path) -> None:
    index = _write_and_index(tmp_path, {"src/a.py": SEED_A, "tests/b.py": SEED_B_OTHER_CALL})
    assert clone_bearing_functions(index) == set()


def test_four_statements_are_below_the_window(tmp_path: Path) -> None:
    four_a = SEED_A.replace("    return principal\n", "")
    four_b = SEED_B.replace("    return who\n", "")
    index = _write_and_index(tmp_path, {"src/a.py": four_a, "tests/b.py": four_b})
    assert clone_bearing_functions(index) == set()


def test_the_same_window_twice_in_one_function_counts_once(tmp_path: Path) -> None:
    twice = "def f(session, name):\n" + _seed_a_statements() * 2
    index = _write_and_index(tmp_path, {"src/a.py": twice})
    assert clone_bearing_functions(index) == set()
    fn = next(node for _, node in iter_functions(ast.parse(twice)))
    windows = function_windows(fn)
    # Ten statements give six windows, at offsets 0 to 5. Offsets 0 and 5 are the same
    # normalized window and collapse to one entry, which keeps the lines of offset 0; offsets
    # 1 to 4 straddle the seam and are four distinct windows, so 1 + 4 = 5.
    assert len(windows) == 5
    assert sorted(windows.values()) == [(2, 6), (3, 7), (4, 8), (5, 9), (6, 10)]


def test_a_window_without_a_call_is_ignored(tmp_path: Path) -> None:
    plain = "def f():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n"
    index = _write_and_index(tmp_path, {"src/a.py": plain, "tests/b.py": plain.replace("def f", "def g")})
    assert clone_bearing_functions(index) == set()


def test_constants_bucket_by_type_and_keep_none_and_bools() -> None:
    a = ast.parse('def f():\n    x = "s"\n    y = 1\n    z = None\n    w = True\n    g(x, y, z, w)\n').body[0]
    b = ast.parse('def f():\n    x = "t"\n    y = 2\n    z = None\n    w = True\n    g(x, y, z, w)\n').body[0]
    c = ast.parse('def f():\n    x = "t"\n    y = 2\n    z = None\n    w = False\n    g(x, y, z, w)\n').body[0]
    assert function_windows(a).keys() == function_windows(b).keys()
    assert function_windows(a).keys() != function_windows(c).keys()


def test_statement_lists_enter_every_compound_body_but_no_nested_scope() -> None:
    source = (
        "if a:\n    s1()\nelse:\n    s2()\n"
        "for x in y:\n    s3()\nelse:\n    s4()\n"
        "while a:\n    s5()\n"
        "with a:\n    s6()\n"
        "try:\n    s7()\nexcept E:\n    s8()\nelse:\n    s9()\nfinally:\n    s10()\n"
        "match a:\n    case 1:\n        s11()\n"
        "def g():\n    nested()\n"
        "class C:\n    nested()\n"
    )
    inner = list(statement_lists(ast.parse(source).body))[1:]
    assert [ast.unparse(stmts[0]) for stmts in inner] == [f"s{i}()" for i in range(1, 12)]


def test_a_window_records_the_lines_it_spans(tmp_path: Path) -> None:
    source = "def f():\n    a()\n    b()\n    c()\n    d()\n    e(\n        1,\n    )\n"
    index = _write_and_index(tmp_path, {"src/a.py": source})
    assert [w for windows in index.values() for w in windows] == [Window(FunctionRef("src/a.py", "f", 1), 2, 8)]


def test_a_copy_inside_an_except_handler_is_found(tmp_path: Path) -> None:
    wrapped = "def outer(session, name):\n    try:\n        pass\n    except ValueError:\n" + _seed_a_statements("    ")
    index = _write_and_index(tmp_path, {"src/a.py": wrapped, "tests/b.py": SEED_B})
    assert FunctionRef("src/a.py", "outer", 1) in clone_bearing_functions(index)


def test_a_copy_inside_a_match_case_is_found(tmp_path: Path) -> None:
    wrapped = "def outer(session, name):\n    match x:\n        case 1:\n" + _seed_a_statements("        ")
    index = _write_and_index(tmp_path, {"src/a.py": wrapped, "tests/b.py": SEED_B})
    assert FunctionRef("src/a.py", "outer", 1) in clone_bearing_functions(index)


def test_a_nested_def_owns_its_window(tmp_path: Path) -> None:
    nested = "def outer():\n" + textwrap.indent(SEED_A, "    ")
    index = _write_and_index(tmp_path, {"src/a.py": nested, "tests/b.py": SEED_B})
    assert clone_bearing_functions(index) == {
        FunctionRef("src/a.py", "outer.seed_tenant", 2),
        FunctionRef("tests/b.py", "seed_other", 1),
    }


def test_an_async_function_is_scanned(tmp_path: Path) -> None:
    index = _write_and_index(tmp_path, {"src/a.py": "async " + SEED_A, "tests/b.py": SEED_B})
    assert clone_bearing_functions(index) == {
        FunctionRef("src/a.py", "seed_tenant", 1),
        FunctionRef("tests/b.py", "seed_other", 1),
    }


def test_skip_parts_are_not_scanned(tmp_path: Path) -> None:
    index = _write_and_index(
        tmp_path, {"src/vendor/a.py": SEED_A, "src/__pycache__/b.py": SEED_B, "tests/c.py": SEED_B}
    )
    assert clone_bearing_functions(index) == set()


def test_an_unparseable_file_raises_naming_it(tmp_path: Path) -> None:
    with pytest.raises(SyntaxError, match=r"src/bad\.py"):
        _write_and_index(tmp_path, {"src/bad.py": "def (:\n"})


def test_groups_are_connected_components(tmp_path: Path) -> None:
    # a shares the seed's five statements with b, and b shares five calls with c.
    calls = "".join(f"    {name}()\n" for name in ("one", "two", "three", "four", "five"))
    index = _write_and_index(
        tmp_path, {"src/a.py": SEED_A, "src/b.py": SEED_B + calls, "src/c.py": "def c():\n" + calls}
    )
    a = FunctionRef("src/a.py", "seed_tenant", 1)
    b = FunctionRef("src/b.py", "seed_other", 1)
    c = FunctionRef("src/c.py", "c", 1)
    assert clone_partners(index) == {a: b, b: a, c: b}  # a and c share no window
    assert clone_groups(index) == [frozenset({a, b, c})]


def test_partners_and_new_pairs(tmp_path: Path) -> None:
    base = _write_and_index(tmp_path / "base", {"src/a.py": SEED_A, "tests/b.py": SEED_B})
    # In head, a blank first line moves seed_tenant to line 2; a function that only moved is not new.
    head = _write_and_index(
        tmp_path / "head",
        {"src/a.py": "\n" + SEED_A, "tests/b.py": SEED_B, "tests/c.py": SEED_B.replace("seed_other", "seed_third")},
    )
    third = FunctionRef("tests/c.py", "seed_third", 1)
    moved = FunctionRef("src/a.py", "seed_tenant", 2)
    assert clone_partners(head)[third] == moved
    assert new_clone_pairs(head, base) == [(third, moved)]


def test_count_by_root_uses_the_longest_root_prefix() -> None:
    fns = {
        FunctionRef(".claude/scripts/x.py", "f", 1),
        FunctionRef("src/a.py", "f", 1),
        FunctionRef("src/b.py", "g", 1),
    }
    assert count_by_root(fns) == {"src": 2, "tests": 0, "scripts": 0, ".pre-commit-hooks": 0, ".claude/scripts": 1}
    # A nested root takes its own files even when the outer root comes first.
    nested = {FunctionRef("scripts/ci/x.py", "f", 1)}
    assert count_by_root(nested, ("scripts", "scripts/ci")) == {"scripts": 0, "scripts/ci": 1}
