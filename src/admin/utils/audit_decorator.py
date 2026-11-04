"""Admin UI action logging decorator.

Automatically logs admin UI actions to the audit_logs table for compliance and visibility.

DECORATOR ORDER CONVENTION:
    @route_decorator
    @require_tenant_access()  # First: Check authorization
    @log_admin_action()       # Second: Log authorized actions only

This order ensures we only log actions by authorized users. The FastAPI side
(``src.admin.web.audit``) gets the same order structurally: the guard is a dependency the
route declares, and the audit wrapper sits directly under the route decorator, so it runs
only once the guard has let the request through. Both sides write the record through
:func:`record_admin_action`, read the caller through :func:`audit_principal`, strip the
form through :func:`sanitize_request_data` and fold a handled refusal through
:func:`fold_handled_failure`: one definition each, so the two cannot drift.
"""

import logging
from collections.abc import Callable, Mapping
from functools import wraps
from typing import Any

from flask import g, request, session

logger = logging.getLogger(__name__)

# Sensitive field patterns to exclude from audit logs
_SENSITIVE_PATTERNS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "secret_key",
        "webhook_secret",
        "signing_secret",
        "token",
        "access_token",
        "refresh_token",
        "bearer_token",
        "api_token",
        "auth_token",
        "key",
        "api_key",
        "apikey",
        "private_key",
        "public_key",
        "priv_key",
        "credential",
        "credentials",
        "authorization",
        "auth",
        "bearer",
        "oauth",
        "oauth_token",
        "oauth_secret",
        "cert",
        "certificate",
    }
)

_SENSITIVE_SUFFIXES = ("_secret", "_token", "_key", "_password", "_credential", "_pwd")


def _is_sensitive_field(field_name: str) -> bool:
    """Check if field name indicates sensitive data.

    Args:
        field_name: Name of the field to check

    Returns:
        True if field is likely to contain sensitive data
    """
    lower_field = field_name.lower()

    # Check exact matches
    if lower_field in _SENSITIVE_PATTERNS:
        return True

    # Check suffixes
    if lower_field.endswith(_SENSITIVE_SUFFIXES):
        return True

    return False


def _sanitize_value(value: Any) -> str:
    """Sanitize and truncate value for audit log storage.

    Args:
        value: Value to sanitize

    Returns:
        Sanitized string (max 100 characters)
    """
    value_str = str(value)
    return value_str[:100] if len(value_str) > 100 else value_str


def sanitize_request_data(data: Mapping[str, Any]) -> dict[str, str]:
    """The non-sensitive fields of a submitted form or JSON body, each value truncated."""
    return {key: _sanitize_value(value) for key, value in data.items() if not _is_sensitive_field(key)}


def _extract_safe_request_data() -> dict[str, str]:
    """Extract non-sensitive data from the Flask request (form or JSON)."""
    if request.form:
        return sanitize_request_data(request.form)
    if request.is_json:
        return sanitize_request_data(request.get_json() or {})
    return {}


def audit_principal(session_data: Mapping[str, Any]) -> str:
    """The email the audit row names: the session's ``user``, or ``"unknown"``."""
    user_info = session_data.get("user", {})
    if isinstance(user_info, dict):
        return str(user_info.get("email", "unknown"))
    return str(user_info) if user_info else "unknown"


def fold_handled_failure(handled: object | None, success: bool, error_message: str | None) -> tuple[bool, str | None]:
    """A refusal the handler declared (see :func:`record_admin_action_failure`) is a failed action."""
    if handled is None:
        return success, error_message
    return False, str(handled)


def record_admin_action(
    audit_logger: Any,
    tenant_id: str,
    operation_name: str,
    *,
    user_email: str,
    method: str,
    request_data: Mapping[str, str],
    success: bool,
    error_message: str | None,
    extra_details: Mapping[str, Any] | None = None,
) -> None:
    """Write one admin audit row. A failed audit write never fails the request."""
    try:
        details: dict[str, Any] = {"user": user_email, "action": operation_name, "method": method}
        if extra_details:
            details.update(extra_details)
        if request_data:
            details["request_data"] = dict(request_data)
        audit_logger.log_operation(
            operation=operation_name,
            principal_name=user_email,
            principal_id=user_email,
            adapter_id="admin_ui",
            success=success,
            details=details,
            error=error_message,
            tenant_id=tenant_id,
        )
    except Exception as e:
        # Don't fail the request if audit logging fails
        logger.warning(f"Failed to write admin audit log for {operation_name}: {e}")


def _get_or_create_audit_logger(tenant_id: str):
    """Get or create audit logger for this request.

    Uses Flask's g object to cache the logger for the request lifecycle,
    reducing database connection overhead.

    Args:
        tenant_id: Tenant ID

    Returns:
        AuditLogger instance
    """
    from src.core.audit_logger import get_audit_logger

    # Cache key includes tenant_id to handle multi-tenant requests
    cache_key = f"audit_logger_{tenant_id}"

    if not hasattr(g, cache_key):
        setattr(g, cache_key, get_audit_logger("AdminUI", tenant_id))

    return getattr(g, cache_key)


_HANDLED_FAILURE_KEY = "_admin_action_failure"


def record_admin_action_failure(error: object) -> None:
    """Mark the current admin action as FAILED even though the handler returns normally.

    A handler that catches its own domain refusal, flashes it, and returns a
    redirect never raises — so :func:`log_admin_action`'s ``except`` never fires
    and ``success`` stays ``True``. The refusal is then written to the audit log
    as a successful admin action.

    That is not hypothetical: ``register_webhook`` refuses an SSRF-blocked URL
    and returns a friendly redirect, and both that shape and its predecessor (a
    return-code check with the same early return) audited as successes.

    Raising instead would be the other fix, and is wrong here: the operator
    should get a flash, not a 500. So the handler says so explicitly.
    """
    g.__setattr__(_HANDLED_FAILURE_KEY, error)


def _apply_handled_failure(success: bool, error_message: str | None) -> tuple[bool, str | None]:
    """Fold a handler-declared failure into the outcome the audit row records.

    Kept out of the wrapper so the branch does not push ``log_admin_action`` past
    the C901 ceiling the repo ratchets (ADR-009 / GH #1610).
    """
    handled = getattr(g, _HANDLED_FAILURE_KEY, None)
    if handled is not None:
        g.__delattr__(_HANDLED_FAILURE_KEY)
    return fold_handled_failure(handled, success, error_message)


def _extracted_details(
    extract_details: Callable[..., dict[str, Any]] | None, operation_name: str, result: Any, kwargs: dict[str, Any]
) -> dict[str, Any] | None:
    """The caller's extra details for the audit row, or ``None``; a failing extractor is logged, not raised."""
    if not (extract_details and callable(extract_details)):
        return None
    try:
        extracted = extract_details(result, **kwargs)
    except Exception as e:
        logger.warning(f"Failed to extract details for {operation_name}: {e}")
        return None
    return extracted if isinstance(extracted, dict) else None


def log_admin_action(
    operation_name: str,
    extract_details: Callable[..., dict[str, Any]] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to log admin UI actions to audit_logs table.

    Args:
        operation_name: Name of the operation (e.g., "update_tenant_settings")
        extract_details: Optional function to extract details from request/response
                        Signature: extract_details(result, **kwargs) -> dict

    Usage:
        @log_admin_action("update_tenant_settings")
        def update_settings(tenant_id):
            # ... implementation ...
            return result

        @log_admin_action("create_product", extract_details=lambda r, **kw: {"product_id": kw.get("product_id")})
        def create_product(tenant_id, product_id):
            # ... implementation ...
            return result
    """

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            user_email = audit_principal(session)

            # The tenant this action belongs to, resolved so it survives either decorator
            # ORDER. Flask hands URL parameters to the OUTERMOST wrapper as kwargs, so
            # reading only kwargs works when this decorator is outermost and silently
            # returns None when it is not: require_tenant_access calls
            # ``f(tenant_id, *args, **kwargs)`` positionally, so tenant_id arrives in args.
            # Since the row is written only ``if tenant_id``, that produced NO audit row at
            # all rather than a wrong one — auditing off, silently, on every route that put
            # authorization outside (which is the order this module's own docstring asks
            # for). request.view_args holds the URL parameters whatever the wrapper chain
            # did with them, so it is the reliable source.
            tenant_id: str | None = kwargs.get("tenant_id") or (request.view_args or {}).get("tenant_id")

            # Call the actual route function
            result: Any = None
            success: bool = True
            error_message: str | None = None

            try:
                result = f(*args, **kwargs)
            except Exception as e:
                # Log failed actions too
                success = False
                error_message = str(e)
                # Re-raise to let Flask handle it
                raise
            finally:
                # A handler that CAUGHT its own refusal and returned normally never
                # reaches the except above. Without this, such a refusal audits as a
                # success — see record_admin_action_failure.
                success, error_message = _apply_handled_failure(success, error_message)

                # Log the admin action (even if it failed)
                if tenant_id:
                    record_admin_action(
                        _get_or_create_audit_logger(tenant_id),
                        tenant_id,
                        operation_name,
                        user_email=user_email,
                        method=request.method,
                        request_data=_extract_safe_request_data() if request.method == "POST" else {},
                        success=success,
                        error_message=error_message,
                        extra_details=_extracted_details(extract_details, operation_name, result, kwargs),
                    )

            return result

        return decorated_function

    return decorator
