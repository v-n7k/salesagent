"""The HTTP status four typed exception classes declare, which nothing else pins.

Everything the boundary DOES with a failure is graded by BDD on the wire and not here:
the code, recovery, field and issues by every error scenario through
``TransportResult.assert_wire_error``; the ``context`` echo and its absence when the
context cannot be modelled by ``local-context-echo-every-outcome.feature``; REST's HTTP
status by the REST-tagged scenarios of ``local-pre-dispatch-refusals.feature``. Anything
asserting an authored ``message``, ``recovery`` or ``suggestion`` is absent too: all three
are read-only properties over ``CODE_TABLE`` (``src/core/errors/codes.py``, built at import
from the pinned adcp SDK's enums), so pinning them per raise site would copy the pinned
table into a second place instead of grading production.

What remains is a fact about the exception CLASSES, not about the boundary: the status each
of these four resolves to through the table, which no scenario names.
``tests/unit/test_adcp_exceptions.py::TestPerClassHttpStatus`` pins a disjoint set of
classes -- the two lists must not overlap.
"""

from __future__ import annotations

import pytest

from src.core.exceptions import (
    AdCPBudgetTooLowError,
    AdCPCapabilityNotSupportedError,
    AdCPMediaBuyNotFoundError,
    AdCPPackageNotFoundError,
    AdCPSalesAgentError,
)


class TestTypedSubclassHttpStatus:
    """The four typed subclasses whose HTTP status nothing else pins."""

    @pytest.mark.parametrize(
        ("exc_cls", "expected_status"),
        [
            (AdCPMediaBuyNotFoundError, 404),
            (AdCPPackageNotFoundError, 404),
            (AdCPBudgetTooLowError, 422),
            (AdCPCapabilityNotSupportedError, 422),
        ],
        ids=lambda value: value.__name__ if isinstance(value, type) else str(value),
    )
    def test_class_declares_its_status(self, exc_cls: type[AdCPSalesAgentError], expected_status: int):
        assert exc_cls().status_code == expected_status
