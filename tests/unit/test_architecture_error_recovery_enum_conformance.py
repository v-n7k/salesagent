"""Oracle: the recovery this platform puts on the wire IS the pinned
``error-code.json`` ``enumMetadata`` recovery classification (#1417).

The ``enumMetadata`` block is normative — its ``$comment`` states: "SDKs MUST
consume this block ... the recovery classification embedded in that prose is
normative and MUST match the value here."

**Why this guard still exists after ADR-010.** The version of this file on
``origin/main`` graded a per-class ``_default_recovery`` literal against the pin.
That literal is gone: ``recovery`` is now a read-only property over
``CODE_TABLE`` (``src/core/errors/codes.py``), and ``__init_subclass__`` refuses
a ``_code`` the table does not classify, so a class can no longer carry a
recovery of its own to drift. Grading a per-class literal here would grade
nothing.

What did NOT become structural is the step underneath it. Every recovery answer
in production — every class, every instance, every envelope — now funnels
through ONE loader, ``codes._load_published_codes()``, reading one block of one
file. That is a single point of failure that nothing else grades: a loader that
resolved the wrong schema bundle, read ``enumDescriptions`` prose instead of the
normative ``enumMetadata``, or fell back to the SDK helper's
``STANDARD_ERROR_CODES`` (which contradicts the pin on 7 of its 38 codes) would
produce a table of entirely plausible size and shape, and every downstream test
that asserts recovery would agree with it — because they all read it. Deleting
this file would have made the loader unenforced, not redundant.

So the obligations kept here are the ones that survive ADR-010, restated against
the merged design:

  * ``CODE_TABLE`` mirrors the pin, code for code, over the pin's full key set;
  * an INSTANCE of every concrete ``AdCPSalesAgentError`` subclass — what the
    envelope builder reads — reports the pinned recovery for its code;
  * the derivation is LIVE at read time, not a literal frozen at construction;
  * ``recovery`` cannot be reassigned onto an instance;
  * the platform-only codes, which sit outside the pin and so escape the oracle
    entirely, are a pinned roster rather than an open door.

Dropped with the symbols they exercised, all deleted by ADR-010 as a second
answer to a question ``CODE_TABLE`` already answers: ``ERROR_CODE_MAPPING`` /
``translate_error_code`` / ``WIRE_STANDARD_CODES`` (boundary translation — the
AdCP code vocabulary is OPEN, codes reach the buyer verbatim),
``RECOVERY_BY_WIRE_CODE`` (a second load of this same block), ``synthesize``
and ``wire_advisory``.

Every expectation below is read from the pin through
``tests.helpers.pinned_schema.recovery_by_code()`` — the ONE test-side reader of
that block — and never from ``src``'s table. That independence from ``src`` is
the load-bearing property: the oracle grades src's loader rather than agreeing
with it.
"""

from __future__ import annotations

import dataclasses

import pytest

from src.core import exceptions
from src.core.errors.codes import CODE_TABLE, AppErrorCode
from src.core.exceptions import AdCPSalesAgentError, AdCPValidationError
from tests.helpers import pinned_schema

_RECOVERY_BY_CODE = pinned_schema.recovery_by_code()

#: Codes this platform emits that AdCP's published enum does not define. They are
#: legal on the wire (the vocabulary is open) but the pin cannot classify them, so
#: they are outside every assertion below. Pinned as a roster so that adding one —
#: which buys a code no spec oracle grades — is a deliberate edit here, not a
#: silent widening of the ungraded set.
_KNOWN_PLATFORM_CODES = frozenset(
    {
        "ACTIVATION_WORKFLOW_FAILED",
        "AD_SERVER_CREATE_FAILED",
        "AD_SERVER_UPDATE_FAILED",
        "AGENT_UNREACHABLE",
        "INTERNAL_ERROR",
        "MEDIA_BUY_REJECTED",
        "PARTIAL_FAILURE",
        "WORKFLOW_CREATION_FAILED",
    }
)


def _code_of(cls: type[AdCPSalesAgentError]) -> str:
    return str(cls._code)


_GRADED_CLASSES = sorted(
    (c for c in AdCPSalesAgentError.iter_concrete_subclasses() if _code_of(c) in _RECOVERY_BY_CODE),
    key=lambda c: c.__name__,
)


def _instance_of(cls: type[AdCPSalesAgentError]) -> AdCPSalesAgentError:
    """An instance of *cls*, built through its own constructor wherever possible.

    A subclass that requires domain keywords still delegates to
    ``AdCPSalesAgentError.__init__``, which sets ``_error_code`` from the class's
    own ``_code`` and never touches recovery — so the fallback reaches the same
    object state this oracle reads. Skipping such a class instead would leave a
    live wire-facing class ungraded.
    """
    try:
        return cls()
    except TypeError:
        instance = cls.__new__(cls)
        AdCPSalesAgentError.__init__(instance)
        return instance


def test_pinned_enum_metadata_loaded() -> None:
    """Meta-guard: the pin loaded and a representative set is graded, so the
    parametrized oracles below can never silently degrade to zero cases."""
    assert len(_RECOVERY_BY_CODE) >= 50, (
        f"Expected the pinned enumMetadata to define recovery for many codes, got {len(_RECOVERY_BY_CODE)}"
    )
    assert len(_GRADED_CLASSES) >= 25, (
        f"Expected to grade many AdCPSalesAgentError subclasses, got {len(_GRADED_CLASSES)}"
    )


def test_code_table_mirrors_pinned_enum() -> None:
    """``CODE_TABLE`` carries the pin's recovery for every published code.

    Exact per-code equality over the pin's full key set, not a size check: a
    loader that resolves the wrong schema bundle, parses the ``Recovery: X``
    clause out of ``enumDescriptions`` prose instead of reading the normative
    ``enumMetadata``, or falls back to the SDK helper's ``STANDARD_ERROR_CODES``
    all produce a table of plausible size. The expectation is loaded
    independently via ``tests.helpers.pinned_schema`` and never read from src's
    table, so this grades src's loader rather than agreeing with it.
    """
    src_table = {str(code): str(entry.recovery) for code, entry in CODE_TABLE.items()}

    missing = sorted(set(_RECOVERY_BY_CODE) - set(src_table))
    assert not missing, (
        f"CODE_TABLE does not classify published code(s) {missing}. Every code in the pinned "
        f"error-code.json enum reaches buyers verbatim (the AdCP code vocabulary is open), so a "
        f"code with no entry makes the recovery answer a KeyError at the moment a caller needs it."
    )

    divergent = {
        code: {"src": src_table[code], "pin": expected}
        for code, expected in sorted(_RECOVERY_BY_CODE.items())
        if src_table[code] != expected
    }
    assert not divergent, (
        f"CODE_TABLE diverges from the pinned error-code.json enumMetadata on "
        f"{len(divergent)} code(s): {divergent}. The enumMetadata block is normative "
        f"($comment: 'SDKs MUST consume this block instead of parsing Recovery: X from "
        f"enumDescriptions prose') — load it at import time; do not hand-type values and do "
        f"not source them from the SDK helper's STANDARD_ERROR_CODES."
    )


def test_platform_only_codes_are_the_pinned_roster() -> None:
    """Codes ``CODE_TABLE`` classifies that the pin does not define are exactly the
    platform roster.

    These are legal on the wire but ungradeable against a spec enum that does not
    contain them, so they escape every assertion above. Pinning the roster means a
    NEW platform code is surfaced for review here rather than silently joining the
    ungraded set.
    """
    unpinned = {str(code) for code in CODE_TABLE if str(code) not in _RECOVERY_BY_CODE}
    assert unpinned == _KNOWN_PLATFORM_CODES, (
        f"CODE_TABLE's non-spec codes are {sorted(unpinned)}, expected {sorted(_KNOWN_PLATFORM_CODES)}. "
        f"A code outside the pinned enum carries a hand-authored recovery no spec oracle grades. "
        f"Either add it to the AdCP error-code enum (and advance the pin), or record it in "
        f"_KNOWN_PLATFORM_CODES here."
    )
    assert unpinned == {str(member) for member in AppErrorCode}, (
        "CODE_TABLE's non-spec codes must be exactly the AppErrorCode members — a published code "
        "shadowed by a platform entry would take its recovery from the platform entry, not the pin."
    )


@pytest.mark.parametrize("cls", _GRADED_CLASSES, ids=lambda c: c.__name__)
def test_instance_recovery_matches_pinned_enum(cls: type[AdCPSalesAgentError]) -> None:
    """Each subclass's INSTANCE recovery — what the envelope builder reads — equals
    the pinned enum's normative value for the class's code."""
    code = _code_of(cls)
    expected = _RECOVERY_BY_CODE[code]
    actual = str(_instance_of(cls).recovery)
    assert actual == expected, (
        f"{cls.__name__} (code {code!r}) reports recovery={actual!r} but the pinned "
        f"error-code.json enumMetadata says {expected!r}. The enumMetadata recovery is "
        f"normative: fix the derivation, or advance the pin if the spec changed."
    )


def test_instance_recovery_follows_the_code_table_at_read_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mirror above is a live derivation, not a coincidence of hand-typed literals.

    Mutation, so the mirror cannot pass vacuously: point the table at a map that
    classifies ``VALIDATION_ERROR`` differently and an instance must FOLLOW it. A
    class that froze its recovery at construction — or copied it into a class
    literal, the channel ADR-010 removed — keeps answering the old value, which is
    exactly the shape where the oracle grades a literal twice and grades no
    derivation at all.
    """
    code = AdCPValidationError._code
    pinned = _RECOVERY_BY_CODE[str(code)]
    flipped = "terminal" if pinned != "terminal" else "transient"
    mutated = dict(CODE_TABLE)
    mutated[code] = dataclasses.replace(CODE_TABLE[code], recovery=flipped)
    monkeypatch.setattr(exceptions, "CODE_TABLE", mutated)

    assert str(AdCPValidationError().recovery) == flipped, (
        f"AdCPValidationError().recovery did not follow CODE_TABLE's entry for {str(code)!r}. "
        f"Recovery must be read from the table at access time; a value frozen at construction "
        f"(or copied into a class literal) is not a derivation, and the mirror above then "
        f"grades nothing."
    )


def test_recovery_cannot_be_reassigned_on_an_instance() -> None:
    """Read-only: the closed constructor channel does not reopen one line later.

    ``exc = AdCPValidationError(); exc.recovery = "terminal"`` is the same
    contradiction as a ``recovery=`` kwarg spelled in two statements, and it
    reaches the envelope builder identically. A property without a setter makes
    the derivation the only answer.
    """
    exc = AdCPValidationError()
    with pytest.raises(AttributeError):
        exc.recovery = "terminal"  # type: ignore[misc]
    assert str(exc.recovery) == _RECOVERY_BY_CODE[str(AdCPValidationError._code)]
