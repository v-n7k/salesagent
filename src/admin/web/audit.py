"""The audit wrapper for a migrated route, and the one place a route reads a form (spec § 5.5, § 5.8).

``audited`` writes the same audit row the Flask ``log_admin_action`` decorator writes, through
the same ``record_admin_action``; it sits directly under the route decorator, above the
endpoint, so it runs only for a request the guard dependency let through. ``form_data`` reads
the request body once and leaves it on ``request.state.form_data``, where the (synchronous)
wrapper finds it: a sync wrapper cannot await the body itself. An endpoint declares it as
``form: Annotated[dict[str, str], Depends(form_data)]`` (ruff's B008 refuses a ``Depends``
call in a default).

A module that defines an ``@audited`` endpoint must not use ``from __future__ import
annotations``: FastAPI resolves a string annotation against the endpoint callable's module
globals, which after ``functools.wraps`` are this module's.
"""

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

from starlette.requests import Request

from src.admin.utils.audit_decorator import (
    audit_principal,
    fold_handled_failure,
    record_admin_action,
    sanitize_request_data,
)
from src.core.audit_logger import get_audit_logger

F = TypeVar("F", bound=Callable[..., Any])


async def form_data(request: Request) -> dict[str, str]:
    """The POSTed form fields (``{}`` for any other method), also left on ``request.state.form_data``."""
    fields: dict[str, str] = {}
    if request.method == "POST":
        fields = {key: value for key, value in (await request.form()).items() if isinstance(value, str)}
    request.state.form_data = fields
    return fields


def record_admin_action_failure(request: Request, error: object) -> None:
    """Mark the current admin action FAILED although the endpoint returns normally.

    The twin of the Flask side's marker: a route that answers its own refusal with a flash
    and a redirect never raises, so without this the refusal would audit as a success.
    """
    request.state.admin_action_failure = error


def audited(operation_name: str) -> Callable[[F], F]:
    """Write one audit row named *operation_name* for every call of the endpoint.

    The endpoint must declare ``request`` and ``tenant_id``; a decorated function that lacks
    either is refused at import, where the mistake is loud.
    """

    def decorator(endpoint: F) -> F:
        parameters = inspect.signature(endpoint).parameters
        if "request" not in parameters or "tenant_id" not in parameters:
            raise TypeError(f"@audited({operation_name!r}) needs an endpoint declaring both request and tenant_id")

        @functools.wraps(endpoint)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request = kwargs["request"]
            tenant_id: str = kwargs["tenant_id"]
            success = True
            error_message: str | None = None
            try:
                return endpoint(*args, **kwargs)
            except Exception as exc:
                success, error_message = False, str(exc)
                raise
            finally:
                handled = getattr(request.state, "admin_action_failure", None)
                success, error_message = fold_handled_failure(handled, success, error_message)
                posted = getattr(request.state, "form_data", {}) if request.method == "POST" else {}
                record_admin_action(
                    get_audit_logger("AdminUI", tenant_id),
                    tenant_id,
                    operation_name,
                    user_email=audit_principal(request.state.session),
                    method=request.method,
                    request_data=sanitize_request_data(posted),
                    success=success,
                    error_message=error_message,
                )

        return cast(F, wrapper)

    return decorator
