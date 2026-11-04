"""The creative-agent and signals-agent routes on the ASGI sub-application (spec § 5.9).

The pilot of the admin convention: one module for the pair, parametrised over the two kinds
by a ``_Pages`` record (templates, route names, the fields each page shows). A route body is
one line: it hands the request to the private body for its operation, which asks the guard
nothing (the guard rides on the route as a dependency), parses the form through the form
model, calls the service, and answers. The one ``except`` in the module is
``except AdminRefusal`` — the service's refusals become a flash-and-redirect (a form) or a
JSON body (an API call); anything else is a crash and stays one.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from src.admin.errors import AdminNotFound, AdminRefusal
from src.admin.forms import parse_form
from src.admin.services.agents import (
    CREATIVE,
    SIGNALS,
    AgentKind,
    create_agent,
    delete_agent,
    probe_agent,
    update_agent,
)
from src.admin.web.audit import audited, form_data
from src.admin.web.guards import require_tenant_access
from src.admin.web.responses import json_error, json_ok, redirect, refuse_form, refuse_json
from src.admin.web.session import flash
from src.admin.web.templates import render, url_for
from src.core.database.repositories.uow import AgentUoW


@dataclass(frozen=True)
class _Pages:
    """What differs between the two kinds' pages: the templates, the route names, the fields shown."""

    kind: AgentKind
    list_template: str
    form_template: str
    list_endpoint: str
    add_endpoint: str
    edit_endpoint: str
    row_fields: tuple[str, ...]  # the list page's per-row keys besides id, has_auth, created_at
    form_fields: tuple[str, ...]  # the edit form's ``agent`` keys besides id


_CREATIVE = _Pages(
    kind=CREATIVE,
    list_template="creative_agents.html",
    form_template="creative_agent_form.html",
    list_endpoint="creative_agents.list_creative_agents",
    add_endpoint="creative_agents.add_creative_agent",
    edit_endpoint="creative_agents.edit_creative_agent",
    row_fields=("agent_url", "name", "enabled", "priority", "auth_type"),
    form_fields=("agent_url", "name", "enabled", "priority", "auth_type", "auth_credentials"),
)

_SIGNALS = _Pages(
    kind=SIGNALS,
    list_template="signals_agents.html",
    form_template="signals_agent_form.html",
    list_endpoint="signals_agents.list_signals_agents",
    add_endpoint="signals_agents.add_signals_agent",
    edit_endpoint="signals_agents.edit_signals_agent",
    row_fields=("agent_url", "name", "enabled", "auth_type", "forward_promoted_offering", "timeout"),
    form_fields=(
        "agent_url",
        "name",
        "enabled",
        "auth_type",
        "auth_header",
        "auth_credentials",
        "forward_promoted_offering",
        "timeout",
    ),
)


# --- the bodies, one per operation ----------------------------------------------------------------


def _tenant(uow: AgentUoW) -> Any:
    assert uow.tenant_config is not None
    return uow.tenant_config.get_tenant()


def _repository(uow: AgentUoW, pages: _Pages) -> Any:
    repository = getattr(uow, pages.kind.repository)
    assert repository is not None
    return repository


def _no_tenant(request: Request) -> Response:
    return refuse_form(request, AdminNotFound("Tenant not found"), url_for(request, "core.index"))


def _row_dict(pages: _Pages, row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        **{name: getattr(row, name) for name in pages.row_fields},
        "has_auth": bool(row.auth_credentials),
        "created_at": row.created_at,
    }


def _list_page(request: Request, pages: _Pages, tenant_id: str) -> Response:
    with AgentUoW(tenant_id) as uow:
        tenant = _tenant(uow)
        if tenant is None:
            return _no_tenant(request)
        rows = _repository(uow, pages).list_all()
        return render(
            request,
            pages.list_template,
            tenant=tenant,
            tenant_id=tenant_id,
            tenant_name=tenant.name,
            custom_agents=[_row_dict(pages, row) for row in rows],
        )


def _add(request: Request, pages: _Pages, tenant_id: str, form: dict[str, str]) -> Response:
    if request.method == "GET":
        with AgentUoW(tenant_id) as uow:
            tenant = _tenant(uow)
            if tenant is None:
                return _no_tenant(request)
            return render(
                request, pages.form_template, tenant=tenant, tenant_id=tenant_id, tenant_name=tenant.name, agent=None
            )
    try:
        name = create_agent(tenant_id, pages.kind, parse_form(pages.kind.form, form))
    except AdminRefusal as exc:
        return refuse_form(request, exc, url_for(request, pages.add_endpoint, tenant_id=tenant_id))
    flash(request, f"{pages.kind.label} agent '{name}' added successfully", "success")
    return redirect(url_for(request, pages.list_endpoint, tenant_id=tenant_id))


def _edit(request: Request, pages: _Pages, tenant_id: str, agent_id: int, form: dict[str, str]) -> Response:
    list_url = url_for(request, pages.list_endpoint, tenant_id=tenant_id)
    if request.method == "GET":
        with AgentUoW(tenant_id) as uow:
            tenant = _tenant(uow)
            if tenant is None:
                return _no_tenant(request)
            row = _repository(uow, pages).get(agent_id)
            if row is None:
                return refuse_form(request, AdminNotFound(f"{pages.kind.label} agent not found"), list_url)
            agent = {"id": row.id, **{name: getattr(row, name) for name in pages.form_fields}}
            return render(
                request, pages.form_template, tenant=tenant, tenant_id=tenant_id, tenant_name=tenant.name, agent=agent
            )
    try:
        name = update_agent(tenant_id, pages.kind, agent_id, parse_form(pages.kind.form, form))
    except AdminRefusal as exc:
        # A missing row goes back to the list, as today; a bad form goes back to the form.
        back_to = (
            list_url
            if isinstance(exc, AdminNotFound)
            else url_for(request, pages.edit_endpoint, tenant_id=tenant_id, agent_id=agent_id)
        )
        return refuse_form(request, exc, back_to)
    flash(request, f"{pages.kind.label} agent '{name}' updated successfully", "success")
    return redirect(list_url)


def _delete(request: Request, pages: _Pages, tenant_id: str, agent_id: int) -> Response:
    try:
        name = delete_agent(tenant_id, pages.kind, agent_id)
    except AdminRefusal as exc:
        return refuse_json(request, exc)
    return json_ok(message=f"{pages.kind.label} agent '{name}' deleted successfully")


def _test(request: Request, pages: _Pages, tenant_id: str, agent_id: int) -> Response:
    try:
        probe = probe_agent(tenant_id, pages.kind, agent_id)
    except AdminRefusal as exc:
        return refuse_json(request, exc)
    if probe.ok:
        return json_ok(**pages.kind.probe_fields(probe))
    return json_error(probe.message, 400)


# --- the routes: the route decorator outermost, the audit under it, the guard on the route ---------

_FORM = Annotated[dict[str, str], Depends(form_data)]
_PAGE = [Depends(require_tenant_access())]
_API = [Depends(require_tenant_access(api_mode=True))]

creative_agents = APIRouter(prefix="/tenant/{tenant_id}/creative-agents")
signals_agents = APIRouter(prefix="/tenant/{tenant_id}/signals-agents")


@creative_agents.get("/", name="creative_agents.list_creative_agents", dependencies=_PAGE)
def list_creative_agents(request: Request, tenant_id: str) -> Response:
    return _list_page(request, _CREATIVE, tenant_id)


@creative_agents.api_route(
    "/add", methods=["GET", "POST"], name="creative_agents.add_creative_agent", dependencies=_PAGE
)
@audited("add_creative_agent")
def add_creative_agent(request: Request, tenant_id: str, form: _FORM) -> Response:
    return _add(request, _CREATIVE, tenant_id, form)


@creative_agents.api_route(
    "/{agent_id}/edit", methods=["GET", "POST"], name="creative_agents.edit_creative_agent", dependencies=_PAGE
)
@audited("edit_creative_agent")
def edit_creative_agent(request: Request, tenant_id: str, agent_id: int, form: _FORM) -> Response:
    return _edit(request, _CREATIVE, tenant_id, agent_id, form)


@creative_agents.delete("/{agent_id}/delete", name="creative_agents.delete_creative_agent", dependencies=_API)
@audited("delete_creative_agent")
def delete_creative_agent(request: Request, tenant_id: str, agent_id: int) -> Response:
    return _delete(request, _CREATIVE, tenant_id, agent_id)


@creative_agents.post("/{agent_id}/test", name="creative_agents.test_creative_agent", dependencies=_API)
@audited("test_creative_agent")
def test_creative_agent(request: Request, tenant_id: str, agent_id: int) -> Response:
    return _test(request, _CREATIVE, tenant_id, agent_id)


@signals_agents.get("/", name="signals_agents.list_signals_agents", dependencies=_PAGE)
def list_signals_agents(request: Request, tenant_id: str) -> Response:
    return _list_page(request, _SIGNALS, tenant_id)


@signals_agents.api_route("/add", methods=["GET", "POST"], name="signals_agents.add_signals_agent", dependencies=_PAGE)
@audited("add_signals_agent")
def add_signals_agent(request: Request, tenant_id: str, form: _FORM) -> Response:
    return _add(request, _SIGNALS, tenant_id, form)


@signals_agents.api_route(
    "/{agent_id}/edit", methods=["GET", "POST"], name="signals_agents.edit_signals_agent", dependencies=_PAGE
)
@audited("edit_signals_agent")
def edit_signals_agent(request: Request, tenant_id: str, agent_id: int, form: _FORM) -> Response:
    return _edit(request, _SIGNALS, tenant_id, agent_id, form)


@signals_agents.delete("/{agent_id}/delete", name="signals_agents.delete_signals_agent", dependencies=_API)
@audited("delete_signals_agent")
def delete_signals_agent(request: Request, tenant_id: str, agent_id: int) -> Response:
    return _delete(request, _SIGNALS, tenant_id, agent_id)


@signals_agents.post("/{agent_id}/test", name="signals_agents.test_signals_agent", dependencies=_API)
@audited("test_signals_agent")
def test_signals_agent(request: Request, tenant_id: str, agent_id: int) -> Response:
    return _test(request, _SIGNALS, tenant_id, agent_id)
