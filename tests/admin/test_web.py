"""The ASGI admin foundation, graded over probe routes (spec § 5.12).

The sub-application is built with a small probe router this module registers itself, plus
two Flask routes added to the admin app, so the foundation is graded before any pilot
router exists: the session both sides share, the link prefix, ``url_for`` in both
directions, ``render`` through Flask's Jinja, the guard dependency and the audit wrapper.

No ``from __future__ import annotations``: FastAPI resolves a string annotation against the
endpoint callable's module globals, which after ``functools.wraps`` are the wrapper's.
"""

from http.cookies import SimpleCookie
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from flask import flash as flask_flash
from flask import get_flashed_messages as flask_get_flashed_messages
from flask import jsonify
from flask import redirect as flask_redirect
from flask import url_for as flask_url_for
from starlette.requests import Request
from starlette.responses import Response

from src.admin.errors import AdminInvalidInput, AdminNotFound
from src.admin.utils.helpers import require_tenant_access as flask_require_tenant_access
from src.admin.web.app import build_admin_app
from src.admin.web.audit import audited, form_data
from src.admin.web.guards import require_tenant_access
from src.admin.web.responses import json_ok, redirect, refuse_form, refuse_json
from src.admin.web.session import flash
from src.admin.web.templates import render, url_for
from src.core.database.repositories.audit_log import AuditLogRepository
from tests.factories.core import TenantFactory
from tests.factories.user import UserFactory
from tests.helpers.admin_session import (
    _session_payload,
    admin_auth_session,
    admin_test_app,
    asgi_auth_session,
    cookie_flashes,
    session_cookie_payload,
    signed_session_cookie,
)

pytestmark = [pytest.mark.admin, pytest.mark.requires_db]

_probe = APIRouter(prefix="/tenant/{tenant_id}/probe")


@_probe.get("/links", name="probe.links")
def probe_links(request: Request, tenant_id: str) -> Response:
    return json_ok(
        flask=url_for(request, "auth.tenant_login", tenant_id=tenant_id),
        router=url_for(request, "probe.links", tenant_id=tenant_id),
        static=url_for(request, "static", filename="validation.css"),
    )


@_probe.get("/page", name="probe.page")
def probe_page(request: Request, tenant_id: str) -> Response:
    return render(request, "base.html", tenant=None, tenant_id=tenant_id)


@_probe.get("/session", name="probe.session")
def probe_session(request: Request, tenant_id: str) -> Response:
    return json_ok(email=request.state.session.get("email"))


@_probe.post("/flash", name="probe.flash")
def probe_flash(request: Request, tenant_id: str) -> Response:
    flash(request, "from-router", "success")
    return redirect(url_for(request, "probe.page", tenant_id=tenant_id))


@_probe.get("/boom", name="probe.boom")
def probe_boom(request: Request, tenant_id: str) -> Response:
    raise RuntimeError("boom-secret")


@_probe.get("/item/{item_id}", name="probe.item")
def probe_item(request: Request, tenant_id: str, item_id: int) -> Response:
    return json_ok(item_id=item_id)


@_probe.get("/guarded", name="probe.guarded", dependencies=[Depends(require_tenant_access())])
def probe_guarded(request: Request, tenant_id: str) -> Response:
    return json_ok()


@_probe.get("/guarded-json", name="probe.guarded_json", dependencies=[Depends(require_tenant_access(api_mode=True))])
def probe_guarded_json(request: Request, tenant_id: str) -> Response:
    return json_ok()


@_probe.post("/audited", name="probe.audited", dependencies=[Depends(require_tenant_access())])
@audited("probe_action")
def probe_audited(request: Request, tenant_id: str, form: Annotated[dict[str, str], Depends(form_data)]) -> Response:
    if form.get("name") == "refuse":
        return refuse_form(request, AdminInvalidInput("nope"), url_for(request, "probe.page", tenant_id=tenant_id))
    return json_ok(name=form.get("name"))


@_probe.post("/audited-json", name="probe.audited_json", dependencies=[Depends(require_tenant_access(api_mode=True))])
@audited("probe_json_action")
def probe_audited_json(
    request: Request, tenant_id: str, form: Annotated[dict[str, str], Depends(form_data)]
) -> Response:
    if form.get("name") == "refuse":
        return refuse_json(request, AdminNotFound("gone"))
    return json_ok()


@pytest.fixture
def flask_app(integration_db):
    app = admin_test_app()

    def probe_flashes(tenant_id):
        return jsonify(flask_get_flashed_messages(with_categories=True))

    def probe_set_flash(tenant_id):
        flask_flash("from-flask", "success")
        return flask_redirect(flask_url_for("probe.page", tenant_id=tenant_id))

    app.add_url_rule("/tenant/<tenant_id>/probe/flashes", "probe_flashes", probe_flashes)
    app.add_url_rule("/tenant/<tenant_id>/probe/set-flash", "probe_set_flash", probe_set_flash)
    app.add_url_rule(
        "/tenant/<tenant_id>/probe/flask-guarded",
        "probe_flask_guarded",
        flask_require_tenant_access()(lambda tenant_id: "ok"),
    )
    return app


@pytest.fixture
def admin_app(flask_app):
    return build_admin_app(flask_app, routers=[_probe])


@pytest.fixture
def client(admin_app):
    return TestClient(admin_app, raise_server_exceptions=False, follow_redirects=False)


@pytest.fixture
def flask_client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def tenant(factory_session):
    return TenantFactory()


def _flask_cookie_to_asgi(flask_client, client) -> None:
    client.cookies.set("session", flask_client.get_cookie("session").value, domain="testserver.local")


def _asgi_cookie_to_flask(response, flask_client) -> None:
    flask_client.set_cookie("session", response.cookies["session"])


def _audit(factory_session, tenant_id: str, operation: str) -> list[tuple]:
    factory_session.rollback()
    return [
        (row.success, row.error_message, (row.details or {}).get("request_data"))
        for row in AuditLogRepository(factory_session, tenant_id).find_by_operation(operation)
    ]


# --- part 1: session, prefix, links, templates, builder ---------------------------------


def test_router_reads_the_session_the_flask_client_wrote(client, flask_client):
    admin_auth_session(flask_client, "t1")
    _flask_cookie_to_asgi(flask_client, client)
    assert client.get("/tenant/t1/probe/session").json() == {"success": True, "email": "test@example.com"}


def test_an_unreadable_cookie_is_an_empty_session(client):
    client.cookies.set("session", "garbage", domain="testserver.local")
    response = client.get("/tenant/t1/probe/session")
    assert (response.status_code, response.json()) == (200, {"success": True, "email": None})


def test_flash_set_by_a_router_is_read_by_the_flask_side(client, flask_client):
    response = client.post("/tenant/t1/probe/flash")
    assert (response.status_code, response.headers["location"]) == (302, "/tenant/t1/probe/page")
    _asgi_cookie_to_flask(response, flask_client)
    assert flask_client.get("/tenant/t1/probe/flashes").get_json() == [["success", "from-router"]]


def test_flash_set_by_flask_shows_on_a_router_rendered_page(client, flask_client, flask_app):
    response = flask_client.get("/tenant/t1/probe/set-flash")
    # Flask resolved a migrated endpoint through the url_build_error_handlers fallback.
    assert (response.status_code, response.headers["Location"]) == (302, "/tenant/t1/probe/page")
    _flask_cookie_to_asgi(flask_client, client)
    page = client.get("/tenant/t1/probe/page")
    assert page.status_code == 200 and "from-flask" in page.text
    # Rendering popped the flash and the cookie was written back without it.
    assert session_cookie_payload(flask_app, page).get("_flashes", []) == []


def test_url_for_resolves_both_sides_under_the_request_prefix(client):
    assert client.get("/tenant/t1/probe/links").json() == {
        "success": True,
        "flask": "/tenant/t1/login",
        "router": "/tenant/t1/probe/links",
        "static": "/static/validation.css",
    }
    prefixed = client.get("/tenant/t1/probe/links", headers={"X-Forwarded-Prefix": "/admin"}).json()
    assert prefixed == {
        "success": True,
        "flask": "/admin/tenant/t1/login",
        "router": "/admin/tenant/t1/probe/links",
        "static": "/admin/static/validation.css",
    }


def test_a_prefix_header_that_is_not_a_plain_path_is_ignored(client):
    links = client.get("/tenant/t1/probe/links", headers={"X-Forwarded-Prefix": "https://attacker.example"}).json()
    assert links["router"] == "/tenant/t1/probe/links"


@pytest.mark.parametrize(
    ("mount", "headers", "prefix"),
    [("/admin", {}, "/admin"), ("", {}, ""), ("", {"X-Forwarded-Prefix": "/admin"}, "/admin")],
    ids=["admin-mount", "root-mount", "admin-host"],
)
def test_the_three_compositions_link_and_redirect_under_their_own_prefix(admin_app, mount, headers, prefix):
    outer = FastAPI()
    outer.mount("/admin", admin_app)
    outer.mount("", admin_app)
    outer_client = TestClient(outer, raise_server_exceptions=False, follow_redirects=False)
    links = outer_client.get(f"{mount}/tenant/t1/probe/links", headers=headers).json()
    assert (links["router"], links["flask"]) == (f"{prefix}/tenant/t1/probe/links", f"{prefix}/tenant/t1/login")
    assert (
        outer_client.post(f"{mount}/tenant/t1/probe/flash", headers=headers).headers["location"]
        == f"{prefix}/tenant/t1/probe/page"
    )
    # base.html links its stylesheet through script_name.
    page = outer_client.get(f"{mount}/tenant/t1/probe/page", headers=headers).text
    assert f'href="{prefix}/static/validation.css"' in page


def test_a_router_written_cookie_carries_the_flask_apps_attributes(client, flask_app):
    morsel = SimpleCookie(client.post("/tenant/t1/probe/flash").headers["set-cookie"])["session"]
    interface = flask_app.session_interface
    assert (morsel["path"], bool(morsel["httponly"]), bool(morsel["secure"]), morsel["samesite"]) == (
        interface.get_cookie_path(flask_app),
        bool(interface.get_cookie_httponly(flask_app)),
        bool(interface.get_cookie_secure(flask_app)),
        interface.get_cookie_samesite(flask_app) or "",
    )


def test_an_unexpected_failure_is_a_plain_500_without_the_exception_text(client):
    response = client.get("/tenant/t1/probe/boom")
    assert response.status_code == 500 and "boom-secret" not in response.text


def test_a_non_integer_path_id_is_404_not_422(client):
    assert client.get("/tenant/t1/probe/item/abc").status_code == 404
    assert client.get("/tenant/t1/probe/item/7").json() == {"success": True, "item_id": 7}


# --- part 2: guard and audit ---------------------------------------------------------------


def test_guard_without_a_session_redirects_to_the_tenant_login_with_next(client):
    response = client.get("/tenant/t1/probe/guarded")
    location = urlsplit(response.headers["location"])
    assert (response.status_code, location.path, parse_qs(location.query)["next"]) == (
        302,
        "/tenant/t1/login",
        ["http://testserver/tenant/t1/probe/guarded"],
    )
    prefixed = urlsplit(
        client.get("/tenant/t1/probe/guarded", headers={"X-Forwarded-Prefix": "/admin"}).headers["location"]
    )
    assert (prefixed.path, parse_qs(prefixed.query)["next"]) == (
        "/admin/tenant/t1/login",
        ["http://testserver/admin/tenant/t1/probe/guarded"],
    )


def test_guard_without_a_session_answers_401_json_under_api_mode(client):
    response = client.get("/tenant/t1/probe/guarded-json")
    assert (response.status_code, response.json()) == (401, {"error": "Authentication required"})


def test_guard_denies_a_user_who_is_not_a_member(client, flask_app, tenant):
    client.cookies.set(
        "session",
        signed_session_cookie(flask_app, {"user": {"email": "nobody@example.com"}}),
        domain="testserver.local",
    )
    assert client.get(f"/tenant/{tenant.tenant_id}/probe/guarded").status_code == 403
    response = client.get(f"/tenant/{tenant.tenant_id}/probe/guarded-json")
    assert (response.status_code, response.json()) == (403, {"error": "Access denied"})


def test_guard_allows_an_active_member(client, flask_app, tenant):
    UserFactory(tenant=tenant, email="member@example.com", is_active=True)
    client.cookies.set(
        "session",
        signed_session_cookie(flask_app, {"user": {"email": "member@example.com"}}),
        domain="testserver.local",
    )
    assert client.get(f"/tenant/{tenant.tenant_id}/probe/guarded").json() == {"success": True}


@pytest.mark.parametrize(
    "payload_for",
    [lambda tid: _session_payload(tid), lambda tid: {}, lambda tid: {"user": {"email": "nobody@example.com"}}],
    ids=["super-admin", "anonymous", "stranger"],
)
def test_guard_answers_the_same_on_both_carriers(client, flask_client, flask_app, tenant, payload_for):
    payload = payload_for(tenant.tenant_id)
    with flask_client.session_transaction() as sess:
        sess.update(payload)
    client.cookies.set("session", signed_session_cookie(flask_app, payload), domain="testserver.local")
    flask_answer = flask_client.get(f"/tenant/{tenant.tenant_id}/probe/flask-guarded")
    asgi_answer = client.get(f"/tenant/{tenant.tenant_id}/probe/guarded")
    assert (flask_answer.status_code, urlsplit(flask_answer.headers.get("Location", "")).path) == (
        asgi_answer.status_code,
        urlsplit(asgi_answer.headers.get("location", "")).path,
    )


def test_audited_route_writes_one_row_with_the_sanitized_form(client, flask_app, tenant, factory_session):
    asgi_auth_session(client, flask_app, tenant.tenant_id)
    response = client.post(f"/tenant/{tenant.tenant_id}/probe/audited", data={"name": "x", "api_key": "secret"})
    assert response.json() == {"success": True, "name": "x"}
    assert _audit(factory_session, tenant.tenant_id, "probe_action") == [(True, None, {"name": "x"})]


def test_refuse_form_flashes_marks_the_audit_failed_and_redirects(client, flask_app, tenant, factory_session):
    asgi_auth_session(client, flask_app, tenant.tenant_id)
    response = client.post(f"/tenant/{tenant.tenant_id}/probe/audited", data={"name": "refuse"})
    assert (response.status_code, response.headers["location"], cookie_flashes(flask_app, response)) == (
        302,
        f"/tenant/{tenant.tenant_id}/probe/page",
        [("error", "nope")],
    )
    assert _audit(factory_session, tenant.tenant_id, "probe_action") == [(False, "nope", {"name": "refuse"})]


def test_refuse_json_answers_the_refusals_status_and_audits_the_failure(client, flask_app, tenant, factory_session):
    asgi_auth_session(client, flask_app, tenant.tenant_id)
    response = client.post(f"/tenant/{tenant.tenant_id}/probe/audited-json", data={"name": "refuse"})
    assert (response.status_code, response.json()) == (404, {"success": False, "error": "gone"})
    assert _audit(factory_session, tenant.tenant_id, "probe_json_action") == [(False, "gone", {"name": "refuse"})]


def test_an_unauthenticated_request_never_reaches_the_audit(client, tenant, factory_session):
    assert client.post(f"/tenant/{tenant.tenant_id}/probe/audited", data={"name": "x"}).status_code == 302
    assert _audit(factory_session, tenant.tenant_id, "probe_action") == []
