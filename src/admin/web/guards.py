"""The tenant-access guard as a FastAPI dependency (spec § 5.8).

The decision is ``tenant_access_decision`` (``src.admin.utils.helpers``), the same function
the Flask decorator calls. This module only carries its two refusals as exceptions and
answers them the way the Flask side does: a 302 to the tenant login (or a 401 JSON body under
``api_mode``) when there is no session, a 403 when the caller is not a member. An unexpected
failure propagates: the sub-application answers a plain 500.
"""

from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from src.admin.utils.helpers import tenant_access_decision
from src.admin.web.responses import redirect
from src.admin.web.templates import request_url, url_for


class AuthRequired(Exception):
    """No session: the caller must log in to *tenant_id* first."""

    def __init__(self, api_mode: bool, tenant_id: str) -> None:
        super().__init__("Authentication required")
        self.api_mode = api_mode
        self.tenant_id = tenant_id


class AccessDenied(Exception):
    """A session, but not a member of the tenant."""

    def __init__(self, api_mode: bool) -> None:
        super().__init__("Access denied")
        self.api_mode = api_mode


def require_tenant_access(api_mode: bool = False) -> Callable[[Request, str], None]:
    """The dependency a route declares: ``dependencies=[Depends(require_tenant_access())]``.

    FastAPI injects ``tenant_id`` from the route's path. On access the guard leaves the caller
    on ``request.state.user`` (the setup-mode user, else the session's ``user``).
    """

    def guard(request: Request, tenant_id: str) -> None:
        access = tenant_access_decision(request.state.session, tenant_id)
        if access.refusal == "login_required":
            raise AuthRequired(api_mode, tenant_id)
        if access.refusal == "denied":
            raise AccessDenied(api_mode)
        request.state.user = access.setup_user if access.setup_user is not None else request.state.session.get("user")

    return guard


def answer_auth_required(request: Request, exc: Exception) -> Response:
    """401 JSON under ``api_mode``, else a 302 to the tenant login carrying ``next=``.

    The JSON bodies keep the Flask guard's shape (``{"error": ...}``, no ``success`` key).
    """
    assert isinstance(exc, AuthRequired)
    if exc.api_mode:
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    return redirect(url_for(request, "auth.tenant_login", tenant_id=exc.tenant_id, next=request_url(request)))


def answer_access_denied(request: Request, exc: Exception) -> Response:
    """403 JSON under ``api_mode``, else a plain 403."""
    assert isinstance(exc, AccessDenied)
    if exc.api_mode:
        return JSONResponse({"error": "Access denied"}, status_code=403)
    return PlainTextResponse("Forbidden", status_code=403)
