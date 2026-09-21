#!/usr/bin/env python3
"""Refresh the pinned AdCP error-code enum vendored here.

Source of truth: adcontextprotocol/adcp @ commit
    467fd93d77112baf9e094e18980119edcd3a4d07  (tag v3.1.1)

This commit is an INTENTIONAL, frozen reference point, DELIBERATELY independent
of the installed adcp SDK's own pin (see docs/adcp-spec-version.md "Pinned
schema sources"). It exists ONLY for enums/error-code.json's ``enumMetadata``
``suggestion`` text, read by
tests/unit/test_architecture_error_suggestion_enum_conformance.py. The
installed SDK's error-code enum has grown independently (92+ codes vs. this
fixture's 64) and its ``suggestion`` wording diverges from this fixture's on
4 codes (CREDENTIAL_IN_ARGS, MEDIA_BUY_NOT_FOUND, PACKAGE_NOT_FOUND,
REQUOTE_REQUIRED, verified at migration time) — moving that reader onto the
SDK tree requires first reconciling that divergence (tracked as
github.com/prebid/salesagent/issues/1883; see docs/adcp-spec-version.md),
not a mechanical resolver swap.

Every OTHER pinned-schema consumer — structural request/response shape,
``$ref`` resolution, AND the ``recovery`` half of this same enumMetadata
block (verified byte-identical across all 64 shared codes, so
tests/harness/transport.py and
tests/unit/test_architecture_error_recovery_enum_conformance.py both migrated)
— reads through tests/helpers/pinned_schema.py, which resolves from the
installed SDK's own tree. scripts/verify_feature_error_codes.py also
migrated (it only reads the ``enum`` code list, not enumMetadata content).
This fixture directory no longer vendors any schema-shape files, only this
one enum, kept only for its suggestion-text divergence.

``$id`` convention (GH #1881)
----------------------------
Vendored files keep upstream's ``$id`` **verbatim** — whatever the pinned
commit ships, byte for byte. ``main()`` refuses to write a file whose fetched
``$id`` is anything else.

Verbatim is the invariant; the concrete form follows the pin. At v3.1.1 that
form is the VERSION-STAMPED ``/schemas/<version>/<category>/<name>.json``
(so ``/schemas/3.1.1/enums/error-code.json``), mirroring the file's own path
under ``dist/schemas/3.1.1/``. Derived from the pin by ``expected_id()`` below
rather than hardcoded, so advancing ``PINNED_SHA``/``PINNED_VERSION`` together
keeps the check honest instead of stale.

The point of this directory is to preserve ONE frozen upstream artifact for
byte-comparison: any field _refresh.py rewrote would no longer be evidence of
what upstream said. That is why the version segment is kept rather than
stripped — stripping it would be this script editing upstream's bytes, the
exact thing the convention exists to prevent.

History: this pin previously sat at 04f59d2d5 (2026-05-13), which predates
3.1.1 and shipped the version-free ``/schemas/<category>/<name>.json`` form.
The vendored copy had drifted from the v3.1.1 enum it claimed to be (65 vs 93
codes, 7+ divergent enumMetadata entries, and an unversioned ``$id``); it was
re-vendored from v3.1.1 verbatim, and this pin advanced to match.

Nothing resolves ``$ref``s against this tree (it holds exactly one leaf enum, and
every ``$ref``-resolving consumer reads the SDK tree via
tests/helpers/pinned_schema.py), so the ``$id`` here is provenance, not routing.
Enforced offline by tests/unit/test_pinned_fixture_id_convention.py.

To refresh (e.g. to advance the pinned commit — a deliberate, reviewed change
that must also re-check the recovery/suggestion divergence against the SDK):
    uv run python tests/fixtures/adcp_schemas_pinned/_refresh.py

It reads from a local clone at ~/projects/adcp if present (faster), else GitHub raw.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from pathlib import Path

PINNED_SHA = "467fd93d77112baf9e094e18980119edcd3a4d07"
PINNED_VERSION = "3.1.1"  # the spec version PINNED_SHA tags; stamped into upstream's own `$id`
REPO = "adcontextprotocol/adcp"
SRC_PREFIX = f"dist/schemas/{PINNED_VERSION}"  # repo path that backs the `/schemas/...` namespace
LOCAL_CLONE = Path.home() / "projects" / "adcp"
FIXTURE_DIR = Path(__file__).parent

# The sole surviving root: error-code enumMetadata (see module docstring for why
# this is a deliberately independent pin, not part of the general schema-shape closure).
ROOTS = [
    "/schemas/enums/error-code.json",
]


def _read_local(rel: str) -> str | None:
    r = subprocess.run(
        ["git", "-C", str(LOCAL_CLONE), "show", f"{PINNED_SHA}:{SRC_PREFIX}{rel}"],
        capture_output=True,
        text=True,
    )
    return r.stdout if r.returncode == 0 else None


def _read_github(rel: str) -> str:
    url = f"https://raw.githubusercontent.com/{REPO}/{PINNED_SHA}/{SRC_PREFIX}{rel}"
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 (pinned host)
        return resp.read().decode()


def fetch(ref: str) -> str:
    rel = ref[len("/schemas") :]  # "/schemas/core/x.json" -> "/core/x.json"
    return _read_local(rel) or _read_github(rel)


class IdConventionError(RuntimeError):
    """A fetched schema's ``$id`` does not follow the vendoring convention."""


def expected_id(ref: str) -> str:
    """Upstream's own ``$id`` for *ref* at the current pin.

    Derived from ``PINNED_VERSION`` rather than hardcoded so that advancing the
    pin cannot leave this check asserting a form the pinned commit stopped
    shipping. ``/schemas/enums/error-code.json`` ->
    ``/schemas/3.1.1/enums/error-code.json``.
    """
    return f"/schemas/{PINNED_VERSION}" + ref[len("/schemas") :]


def check_id_convention(ref: str, schema: dict) -> None:
    """Raise unless *schema*'s ``$id`` is verbatim what the pinned commit ships.

    See the module docstring's "$id convention" section. Called before writing,
    so a refresh that would change the vendored ``$id`` aborts loudly instead of
    silently regressing the file and being caught (if at all) by a downstream
    reader much later.
    """
    actual = schema.get("$id")
    expected = expected_id(ref)
    if actual != expected:
        raise IdConventionError(
            f"{ref}: upstream $id is {actual!r}, expected {expected!r}. Vendored fixtures keep "
            f"upstream's $id verbatim; at v{PINNED_VERSION} that is the version-stamped "
            f"/schemas/<version>/<category>/<name>.json form (GH #1881). "
            f"If upstream deliberately changed its $id convention, update this script's "
            f"docstring and tests/unit/test_pinned_fixture_id_convention.py in the same "
            f"reviewed change — do not vendor the new form silently."
        )


def main() -> None:
    seen: set[str] = set()
    stack = list(ROOTS)
    written = 0
    while stack:
        ref = stack.pop().split("#")[0]
        if not ref.startswith("/schemas/") or ref in seen:
            continue
        seen.add(ref)
        body = fetch(ref)
        schema = json.loads(body)
        check_id_convention(ref, schema)
        out = FIXTURE_DIR / ref[len("/schemas/") :]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(schema, indent=2) + "\n")
        written += 1
        stack.extend(re.findall(r'"\$ref"\s*:\s*"([^"]+)"', body))
    print(f"vendored {written} schema files from {REPO}@{PINNED_SHA[:9]} into {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
