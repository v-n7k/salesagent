"""The admin refusal family: one exception class per HTTP status a route may answer.

A service raises one of these when the operator's request cannot be honoured (a missing
row, a bad field, a conflicting state); the router answers it with ``refuse_form`` or
``refuse_json`` (``src.admin.web.responses``), which carry the message to the operator and
mark the audit row failed. The message is authored at the raise site: this is the
operator-facing admin surface, not the buyer wire, so there is no code table to look up.
Imports nothing from any framework, so services and forms can raise without knowing how
the answer travels.
"""

from typing import ClassVar


class AdminRefusal(Exception):
    """A request the admin cannot honour; ``status`` is the HTTP status the answer carries."""

    status: ClassVar[int] = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AdminNotFound(AdminRefusal):
    """The row the request names does not exist for this tenant."""

    status = 404


class AdminInvalidInput(AdminRefusal):
    """A field of the request is missing, malformed, or refused by policy."""

    status = 400


class AdminConflict(AdminRefusal):
    """The request contradicts the stored state."""

    status = 409
