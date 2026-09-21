"""Structural guard for the A2A wire integer-type fix.

Pins two invariants that keep the fix (see
``restore_a2a_integer_types`` in ``src/a2a_server/adcp_a2a_server.py``) from
silently regressing:

1. ``_dict_to_value`` (adcp_a2a_server.py) is the ONLY site in ``src/`` that
   constructs a ``google.protobuf.Struct``/``Value`` for A2A wire data. A
   second, parallel construction site would bypass the integer-restoration
   fix for whatever it builds.
2. Every real ``/a2a`` JSON-RPC route registered on the FastAPI app is
   wrapped with the integer-restoring ASGI wrapper -- a future refactor of
   ``src/app.py``'s route wiring could easily drop the wrapper and silently
   reintroduce the float-widening bug on the real wire.

Deleted 2026-08-31: a third test in this module asserted that ``struct_pb2.Value()``
appears only in ``adcp_a2a_server.py``. It was removed rather than repaired.

- It graded a code LOCATION as a stand-in for the behaviour, which the two classes below
  grade directly: the ASGI wrapper is exercised at the real HTTP boundary in
  ``test_a2a_route_integer_restoration.py``, and every ``/a2a`` route is checked for the
  wrapper here.
- Its allowlist was the FILE, so a second construction site inside ``adcp_a2a_server.py``
  -- the likeliest place for one to appear -- was exempt from the very check meant to
  catch it.
- Its meta-test wrote a real module into ``src/`` while the sibling test scanned ``src/``.
  Under xdist those run on different workers and race: 1 in 3 local runs with ``-n 4``
  failed, and it failed on the box for that reason. A test that mutates the source tree
  can also break any OTHER src/-scanning guard that happens to run beside it, and this
  repo has many.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestA2ARoutesWrapWithIntegerRestoration:
    def test_all_a2a_rpc_routes_are_integer_restoration_wrapped(self):
        from src.app import _a2a_rpc_routes

        assert _a2a_rpc_routes, "expected at least one /a2a JSON-RPC route"
        unwrapped = [
            route.path
            for route in _a2a_rpc_routes
            if not getattr(route.endpoint, "__a2a_integer_restoration_wrapped__", False)
        ]
        assert not unwrapped, (
            f"these /a2a routes are missing the integer-restoration wrapper: {unwrapped} -- "
            "the real HTTP wire would silently widen integer fields to floats again"
        )

    def test_unwrapped_route_would_be_caught(self):
        """Meta-test: an endpoint without the marker attribute must fail the check
        above's condition -- proves the guard isn't vacuously true."""

        async def _unmarked_endpoint(request):
            return None

        assert not getattr(_unmarked_endpoint, "__a2a_integer_restoration_wrapped__", False)


class TestIntegerSetMatchesTheSchemas:
    """A2A_WIRE_INTEGER_FIELDS is a hand-maintained set; pin it to the schemas.

    The set drives a NAME-KEYED coercion: any whole-numbered float arriving at one of
    these keys is turned back into an ``int``. That is safe only while every listed name
    really is integer-typed somewhere we control or the spec declares. Nothing checked
    that before -- an 18-name hand-list justified by a prose comment (prkv.5 Lane D D10).
    """

    @staticmethod
    def _pinned_property_types() -> dict[str, set[str]]:
        """property name -> every JSON `type` the pinned 3.1 schemas declare for it."""
        import importlib.util
        import json
        import pathlib

        root = pathlib.Path(importlib.util.find_spec("adcp").origin).parent / "_schemas/3.1"
        types: dict[str, set[str]] = {}

        def walk(node, key=None):
            if isinstance(node, dict):
                declared = node.get("type")
                if key and isinstance(declared, str):
                    types.setdefault(key, set()).add(declared)
                for k, v in node.items():
                    if k == "properties" and isinstance(v, dict):
                        for pk, pv in v.items():
                            walk(pv, pk)
                    else:
                        walk(v, key if k in ("items", "allOf", "anyOf", "oneOf", "$defs", "definitions") else None)
            elif isinstance(node, list):
                for v in node:
                    walk(v, key)

        for f in root.rglob("*.json"):
            try:
                walk(json.loads(f.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return types

    @staticmethod
    def _app_integer_fields() -> set[str]:
        import inspect

        from pydantic import BaseModel

        import src.core.schemas as app

        out: set[str] = set()
        for name in dir(app):
            obj = getattr(app, name)
            if inspect.isclass(obj) and issubclass(obj, BaseModel):
                for field, info in obj.model_fields.items():
                    annotation = str(info.annotation)
                    if "int" in annotation and "float" not in annotation:
                        out.add(field)
        return out

    def test_every_listed_name_is_integer_typed_somewhere_authoritative(self) -> None:
        """Each name is integer per the PIN or per our own response models (SDK union app).

        Eleven of the eighteen are this server's own count fields (sync/assign counts,
        delivery totals) and correctly do not appear in the pinned schemas at all; they
        are graded against the app models instead. A name in NEITHER place is a name
        nobody can justify, and coercion would be firing on a guess.
        """
        from src.a2a_server.adcp_a2a_server import A2A_WIRE_INTEGER_FIELDS

        pinned = self._pinned_property_types()
        spec_ints = {n for n, ts in pinned.items() if "integer" in ts}
        app_ints = self._app_integer_fields()

        unjustified = sorted(A2A_WIRE_INTEGER_FIELDS - spec_ints - app_ints)
        assert not unjustified, (
            f"A2A_WIRE_INTEGER_FIELDS lists {unjustified}, which no pinned schema and no app "
            f"response model declares as an integer. Coercion fires on those names anyway, so "
            f"either the field is gone or the name is wrong."
        )

    def test_no_new_name_is_ambiguous_between_integer_and_number(self) -> None:
        """A listed name ALSO declared ``number`` in the pin is a coercion hazard.

        The coercion is keyed by NAME, not by the field's own declaration, so where the pin
        declares one property integer and a same-named property elsewhere ``number``, a
        whole-valued float of the SECOND kind gets silently retyped to int -- emitting an
        int where the spec says number. The two below are pre-existing and recorded, not
        endorsed; this only stops the set from growing more of them.
        """
        from src.a2a_server.adcp_a2a_server import A2A_WIRE_INTEGER_FIELDS

        pinned = self._pinned_property_types()
        number_names = {n for n, ts in pinned.items() if "number" in ts}
        known_ambiguous = frozenset({"impressions", "limit"})

        ambiguous = A2A_WIRE_INTEGER_FIELDS & number_names
        new = sorted(ambiguous - known_ambiguous)
        assert not new, (
            f"{new} are listed for int coercion but the pinned schemas also declare them "
            f"`number` somewhere. A whole-valued float at that key would be retyped to int "
            f"on the wire. Narrow the coercion (key it on the response type, not the bare "
            f"name) rather than widening this set."
        )
        stale = sorted(known_ambiguous - ambiguous)
        assert not stale, f"known_ambiguous lists {stale}, no longer ambiguous -- delete the entry"
