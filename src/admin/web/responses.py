"""The admin's response helpers: one JSON envelope, one redirect status (spec § 5.6).

Every JSON answer a migrated route gives is ``{"success": true, ...}`` or
``{"success": false, "error": "<message>"}``; every redirect is a 302 (Starlette's
``RedirectResponse`` defaults to 307, which would replay a POST). A route calls these and
never builds a response by hand.
"""

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from src.admin.errors import AdminRefusal
from src.admin.web.audit import record_admin_action_failure
from src.admin.web.session import flash


def json_ok(**fields: Any) -> JSONResponse:
    """A 200 whose body is ``{"success": true}`` plus *fields*."""
    return JSONResponse({"success": True, **fields})


def json_error(message: str, status: int) -> JSONResponse:
    """A *status* answer whose body is ``{"success": false, "error": message}``."""
    return JSONResponse({"success": False, "error": message}, status_code=status)


def redirect(url: str) -> RedirectResponse:
    """A 302 to *url*."""
    return RedirectResponse(url, status_code=302)


def refuse_json(request: Request, exc: AdminRefusal) -> JSONResponse:
    """Answer a refusal on a JSON route: its status and message, and the audit row marked failed."""
    record_admin_action_failure(request, exc)
    return json_error(exc.message, exc.status)


def refuse_form(request: Request, exc: AdminRefusal, back_to: str) -> RedirectResponse:
    """Answer a refusal on a form route: flash the message, mark the audit row failed, go back."""
    flash(request, exc.message, "error")
    record_admin_action_failure(request, exc)
    return redirect(back_to)
