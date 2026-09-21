"""The test-credential login path.

Registered by ``create_app`` only where the deployment allows it
(``ADCP_AUTH_TEST_MODE`` set and not production): the routes EXIST there and nowhere else,
so no route here asks what environment it is in. A request-time reader that needs to know
whether this path was composed asks the app (:func:`src.admin.utils.helpers.test_login_composed`).
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import select

from src.admin.blueprints.auth import _safe_redirect
from src.admin.utils.helpers import TEST_LOGIN_BLUEPRINT
from src.core.config import get_settings
from src.core.config_loader import is_single_tenant_mode
from src.core.database.database_session import get_db_session
from src.core.database.models import Tenant

logger = logging.getLogger(__name__)

test_auth_bp = Blueprint(TEST_LOGIN_BLUEPRINT, __name__)


@test_auth_bp.route("/test/auth", methods=["POST"])
def test_auth():
    """Log in with a test credential.

    The route is composed only under the global deployment flag; the requested tenant
    must ALSO still be in setup mode (auth_setup_mode). A tenant operator disabling
    Setup Mode via the Admin UI immediately blocks test auth for that tenant.
    """
    email = request.form.get("email", "").lower()
    password = request.form.get("password")
    tenant_id = request.form.get("tenant_id")

    # In single-tenant mode, default to "default" tenant if not specified
    if is_single_tenant_mode() and not tenant_id:
        tenant_id = "default"

    tenant_setup_mode = False
    if tenant_id:
        with get_db_session() as db_session:
            tenant = db_session.scalars(select(Tenant).filter_by(tenant_id=tenant_id)).first()
            if tenant and hasattr(tenant, "auth_setup_mode"):
                tenant_setup_mode = tenant.auth_setup_mode

    # The tenant operator's decision to disable Setup Mode via the UI is respected (F-02).
    if not tenant_setup_mode:
        logger.warning(
            "[SECURITY] test_auth blocked for tenant %r: auth_setup_mode is disabled. "
            "Re-enable Setup Mode or configure SSO.",
            tenant_id,
        )
        abort(404)

    # Define test users — credentials come from the settings, never hardcoded
    testing = get_settings().testing
    test_users = {
        testing.test_super_admin_email: {
            "password": testing.test_super_admin_password,
            "name": "Test Super Admin",
            "role": "super_admin",
        },
        testing.test_tenant_admin_email: {
            "password": testing.test_tenant_admin_password,
            "name": "Test Tenant Admin",
            "role": "tenant_admin",
        },
        testing.test_tenant_user_email: {
            "password": testing.test_tenant_user_password,
            "name": "Test Tenant User",
            "role": "tenant_user",
        },
    }

    # Check test users — all credentials go through the test_users table, no bypasses
    if email in test_users and test_users[email]["password"] == password:
        user_info = test_users[email]
        session["test_user"] = email
        session["test_user_name"] = user_info["name"]
        session["test_user_role"] = user_info["role"]
        session["user"] = email
        session["user_name"] = user_info["name"]
        session["role"] = user_info["role"]
        session["authenticated"] = True
        session["email"] = email

        if user_info["role"] == "super_admin":
            session["is_super_admin"] = True

        if tenant_id:
            session["test_tenant_id"] = tenant_id
            session["tenant_id"] = tenant_id
            next_url = _safe_redirect(
                session.pop("login_next_url", None),
                fallback=url_for("tenants.dashboard", tenant_id=tenant_id),
            )
            return redirect(next_url)
        next_url = _safe_redirect(session.pop("login_next_url", None), fallback=url_for("core.index"))
        return redirect(next_url)

    flash("Invalid test credentials", "error")
    return redirect(request.referrer or url_for("auth.login"))


@test_auth_bp.route("/test/login")
def test_login_form():
    """Show the test login form. For per-tenant setup mode, use /tenant/<tenant_id>/login."""
    return render_template("login.html", test_mode=True, test_only=True, single_tenant_mode=is_single_tenant_mode())
