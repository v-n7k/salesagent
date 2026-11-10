"""The creative-agent and signals-agent routes on the ASGI sub-application (spec § 5.9).

One module for the pair, parametrised over the two kinds: the same ten routes, the same
service, the same shape of answer. Every write is checked three ways: the operator's answer
(status, redirect target, flashed sentence), the stored rows read through the repository,
and the audit row. The probe is the one patched seam (``_probe``): the registry's own
``probe_agent`` is replaced on the registry class, so nothing is dialed.
"""

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

import pytest

from src.core.database.repositories.audit_log import AuditLogRepository
from src.core.database.repositories.uow import AgentUoW
from src.core.utils.operator_mcp import ProbeResult
from tests.factories.core import CreativeAgentFactory, SignalsAgentFactory, TenantFactory
from tests.helpers.admin_session import asgi_auth_session, cookie_flashes
from tests.helpers.egress_hatches import UNDIALLED_PUBLIC_HTTPS_ORIGIN
from tests.helpers.settings_injection import inject_limits

pytestmark = [pytest.mark.admin, pytest.mark.requires_db]

AGENT_URL = f"{UNDIALLED_PUBLIC_HTTPS_ORIGIN}/mcp"
BLOCKED_URL = "https://169.254.169.254/agent"
EGRESS_SENTENCE = "Agent URL is not allowed by outbound egress policy."
SUCCESS_MESSAGE = "Connected to Optable, 42 formats available"
FAILURE_MESSAGE = "Connection failed: handshake rejected by the endpoint"
SAMPLE_FORMATS = ("display_300x250_image", "video_16x9_15s", "audio_30s")


@dataclass(frozen=True)
class _Case:
    label: str
    key: str
    prefix: str
    factory: Any
    repository: str
    probe_target: str
    number_field: str
    kind_fields: tuple[tuple[str, Any], ...]
    probe_success_body: dict[str, Any]
    probe_no_count_body: dict[str, Any]
    probe_success_result: ProbeResult
    probe_no_count_result: ProbeResult


CREATIVE_CASE = _Case(
    label="Creative",
    key="creative",
    prefix="creative-agents",
    factory=CreativeAgentFactory,
    repository="creative_agents",
    probe_target="src.core.creative_agent_registry.CreativeAgentRegistry.probe_agent",
    number_field="priority",
    kind_fields=(("priority", 10),),
    probe_success_body={
        "success": True,
        "message": SUCCESS_MESSAGE,
        "format_count": 42,
        "sample_formats": list(SAMPLE_FORMATS),
    },
    probe_no_count_body={"success": True, "message": SUCCESS_MESSAGE, "format_count": None, "sample_formats": []},
    probe_success_result=ProbeResult(ok=True, message=SUCCESS_MESSAGE, count=42, samples=SAMPLE_FORMATS),
    probe_no_count_result=ProbeResult(ok=True, message=SUCCESS_MESSAGE),
)

SIGNALS_CASE = _Case(
    label="Signals",
    key="signals",
    prefix="signals-agents",
    factory=SignalsAgentFactory,
    repository="signals_agents",
    probe_target="src.core.signals_agent_registry.SignalsAgentRegistry.probe_agent",
    number_field="timeout",
    kind_fields=(("forward_promoted_offering", False),),
    probe_success_body={"success": True, "message": SUCCESS_MESSAGE, "signal_count": 37},
    probe_no_count_body={"success": True, "message": SUCCESS_MESSAGE, "signal_count": None},
    probe_success_result=ProbeResult(ok=True, message=SUCCESS_MESSAGE, count=37),
    probe_no_count_result=ProbeResult(ok=True, message=SUCCESS_MESSAGE),
)


@pytest.fixture(params=[CREATIVE_CASE, SIGNALS_CASE], ids=["creative", "signals"])
def case(request):
    return request.param


@pytest.fixture
def tenant(factory_session):
    return TenantFactory()


@pytest.fixture
def flask_app(asgi_admin_app):
    return asgi_admin_app.state.flask_app


@pytest.fixture
def client(asgi_admin_client, flask_app, tenant):
    asgi_auth_session(asgi_admin_client, flask_app, tenant.tenant_id)
    return asgi_admin_client


@pytest.fixture
def agent(case, tenant):
    return case.factory(
        tenant=tenant, agent_url=AGENT_URL, auth_credentials="secret-1", auth_header="x-api-key", timeout=45
    )


def _answer(flask_app, response) -> tuple[int, str, list[tuple[str, str]]]:
    return response.status_code, response.headers.get("location", ""), cookie_flashes(flask_app, response)


def _rows(case: _Case, tenant_id: str) -> list[tuple]:
    with AgentUoW(tenant_id) as uow:
        repository = getattr(uow, case.repository)
        return [
            (
                row.name,
                row.enabled,
                row.auth_type,
                row.auth_credentials,
                row.auth_header,
                row.timeout,
                tuple((name, getattr(row, name)) for name, _ in case.kind_fields),
            )
            for row in repository.list_all()
        ]


def _audit(factory_session, tenant_id: str, operation: str) -> list[tuple]:
    factory_session.rollback()
    return [
        (row.success, row.error_message)
        for row in AuditLogRepository(factory_session, tenant_id).find_by_operation(operation)
    ]


def _probe(case: _Case, outcome):
    """Replace the registry's probe with one answer (a ``ProbeResult``) or one failure (an exception)."""
    probe = AsyncMock(side_effect=outcome) if isinstance(outcome, BaseException) else AsyncMock(return_value=outcome)
    return patch(case.probe_target, new=probe)


# --- pages -------------------------------------------------------------------------------------


def test_list_page_shows_the_seeded_agent(client, case, tenant, agent):
    response = client.get(f"/tenant/{tenant.tenant_id}/{case.prefix}/")
    assert response.status_code == 200 and agent.name in response.text


def test_add_form_renders(client, case, tenant):
    assert client.get(f"/tenant/{tenant.tenant_id}/{case.prefix}/add").status_code == 200


# --- add ---------------------------------------------------------------------------------------


def test_add_stores_the_row_with_typed_defaults(client, flask_app, case, tenant, factory_session):
    response = client.post(
        f"/tenant/{tenant.tenant_id}/{case.prefix}/add",
        data={"agent_url": AGENT_URL, "name": "  Spaced  ", "enabled": "on", "csrf_token": "x"},
    )
    assert _answer(flask_app, response) == (
        302,
        f"/tenant/{tenant.tenant_id}/{case.prefix}/",
        [("success", f"{case.label} agent 'Spaced' added successfully")],
    )
    assert _rows(case, tenant.tenant_id) == [("Spaced", True, None, None, None, 30, case.kind_fields)]
    assert _audit(factory_session, tenant.tenant_id, f"add_{case.key}_agent") == [(True, None)]


def test_add_without_a_name_is_refused(client, flask_app, case, tenant):
    response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/add", data={"agent_url": AGENT_URL})
    assert _answer(flask_app, response) == (
        302,
        f"/tenant/{tenant.tenant_id}/{case.prefix}/add",
        [("error", "Agent name is required")],
    )
    assert _rows(case, tenant.tenant_id) == []


def test_add_with_a_blank_url_is_refused(client, flask_app, case, tenant):
    response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/add", data={"agent_url": "  ", "name": "x"})
    assert _answer(flask_app, response) == (
        302,
        f"/tenant/{tenant.tenant_id}/{case.prefix}/add",
        [("error", "Agent URL is required")],
    )
    assert _rows(case, tenant.tenant_id) == []


def test_add_with_a_non_integer_number_is_refused(client, flask_app, case, tenant):
    response = client.post(
        f"/tenant/{tenant.tenant_id}/{case.prefix}/add",
        data={"agent_url": AGENT_URL, "name": "x", case.number_field: "abc"},
    )
    sentence = (
        f"{case.number_field.capitalize()}: Input should be a valid integer, unable to parse string as an integer"
    )
    assert _answer(flask_app, response) == (302, f"/tenant/{tenant.tenant_id}/{case.prefix}/add", [("error", sentence)])
    assert _rows(case, tenant.tenant_id) == []


def test_add_refuses_a_url_egress_policy_blocks_and_audits_the_refusal(
    client, flask_app, case, tenant, monkeypatch, factory_session
):
    inject_limits(monkeypatch, adcp_outbound_allow_private=False)
    response = client.post(
        f"/tenant/{tenant.tenant_id}/{case.prefix}/add", data={"agent_url": BLOCKED_URL, "name": "x"}
    )
    assert _answer(flask_app, response) == (
        302,
        f"/tenant/{tenant.tenant_id}/{case.prefix}/add",
        [("error", EGRESS_SENTENCE)],
    )
    assert _rows(case, tenant.tenant_id) == []
    assert _audit(factory_session, tenant.tenant_id, f"add_{case.key}_agent") == [(False, EGRESS_SENTENCE)]


# --- edit --------------------------------------------------------------------------------------


def test_edit_updates_the_row_and_keeps_blank_credentials(client, flask_app, case, tenant, agent):
    data = {"agent_url": AGENT_URL, "name": "Renamed", "enabled": "on", "auth_type": "bearer", "auth_credentials": ""}
    if case.key == "signals":
        data |= {"auth_header": "x-api-key", "timeout": "45"}
    response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id}/edit", data=data)
    assert _answer(flask_app, response) == (
        302,
        f"/tenant/{tenant.tenant_id}/{case.prefix}/",
        [("success", f"{case.label} agent 'Renamed' updated successfully")],
    )
    # creative: auth_header and timeout come from the fixture and survive an edit whose form has no such
    # fields; priority stays at the form default. signals: both values come from the form.
    assert _rows(case, tenant.tenant_id) == [("Renamed", True, "bearer", "secret-1", "x-api-key", 45, case.kind_fields)]


def test_edit_unchecks_a_checkbox_when_the_field_is_absent(client, flask_app, case, tenant, agent):
    response = client.post(
        f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id}/edit", data={"agent_url": AGENT_URL, "name": agent.name}
    )
    assert response.status_code == 302
    assert [(row[1], row[6]) for row in _rows(case, tenant.tenant_id)] == [(False, case.kind_fields)]


def test_edit_of_an_unknown_id_redirects_to_the_list(client, flask_app, case, tenant, agent):
    response = client.post(
        f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id + 9999}/edit", data={"agent_url": AGENT_URL, "name": "x"}
    )
    assert _answer(flask_app, response) == (
        302,
        f"/tenant/{tenant.tenant_id}/{case.prefix}/",
        [("error", f"{case.label} agent not found")],
    )


# --- delete ------------------------------------------------------------------------------------


def test_delete_removes_the_row_and_audits(client, case, tenant, agent, factory_session):
    response = client.delete(f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id}/delete")
    assert (response.status_code, response.json()) == (
        200,
        {"success": True, "message": f"{case.label} agent '{agent.name}' deleted successfully"},
    )
    assert _rows(case, tenant.tenant_id) == []
    assert _audit(factory_session, tenant.tenant_id, f"delete_{case.key}_agent") == [(True, None)]


def test_delete_of_an_unknown_id_is_404_and_audits_as_a_failure(client, case, tenant, agent, factory_session):
    response = client.delete(f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id + 9999}/delete")
    assert (response.status_code, response.json()) == (
        404,
        {"success": False, "error": f"{case.label} agent not found"},
    )
    assert _audit(factory_session, tenant.tenant_id, f"delete_{case.key}_agent") == [
        (False, f"{case.label} agent not found")
    ]


def test_delete_cannot_reach_another_tenants_agent(client, case, tenant):
    other = case.factory(tenant=TenantFactory(), agent_url=AGENT_URL)
    response = client.delete(f"/tenant/{tenant.tenant_id}/{case.prefix}/{other.id}/delete")
    assert (response.status_code, response.json()) == (
        404,
        {"success": False, "error": f"{case.label} agent not found"},
    )
    assert [row[0] for row in _rows(case, other.tenant_id)] == [other.name]


# --- probe -------------------------------------------------------------------------------------


def test_probe_success_projects_every_field_onto_the_template_keys(client, case, tenant, agent):
    with _probe(case, case.probe_success_result):
        response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id}/test")
    assert (response.status_code, response.json()) == (200, case.probe_success_body)


def test_probe_failure_puts_the_sentence_under_error(client, case, tenant, agent):
    with _probe(case, ProbeResult(ok=False, message=FAILURE_MESSAGE)):
        response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id}/test")
    assert (response.status_code, response.json()) == (400, {"success": False, "error": FAILURE_MESSAGE})


def test_probe_success_without_a_count_stays_null_on_the_wire(client, case, tenant, agent):
    with _probe(case, case.probe_no_count_result):
        response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id}/test")
    assert (response.status_code, response.json()) == (200, case.probe_no_count_body)


def test_probe_of_an_unknown_id_is_404(client, case, tenant, agent):
    with _probe(case, case.probe_success_result):
        response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id + 9999}/test")
    assert (response.status_code, response.json()) == (
        404,
        {"success": False, "error": f"{case.label} agent not found"},
    )


def test_probe_refuses_a_stored_url_egress_policy_blocks_without_dialing(client, case, tenant, monkeypatch):
    blocked = case.factory(tenant=tenant, agent_url=BLOCKED_URL)
    inject_limits(monkeypatch, adcp_outbound_allow_private=False)
    with _probe(case, case.probe_success_result) as probe:
        response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/{blocked.id}/test")
    assert (response.status_code, response.json(), probe.await_count) == (
        400,
        {"success": False, "error": EGRESS_SENTENCE},
        0,
    )


def test_probe_crash_is_a_plain_500_without_the_exception_text(client, case, tenant, agent):
    with _probe(case, RuntimeError("boom-secret")):
        response = client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/{agent.id}/test")
    assert response.status_code == 500 and "boom-secret" not in response.text


def test_a_non_integer_agent_id_is_404(client, case, tenant):
    assert client.post(f"/tenant/{tenant.tenant_id}/{case.prefix}/abc/test").status_code == 404


# --- the guard, once each on the anonymous client (the guard is not the pilot's subject) -------


def test_unauthenticated_html_request_redirects_to_login(asgi_admin_client, tenant):
    response = asgi_admin_client.get(f"/tenant/{tenant.tenant_id}/creative-agents/")
    assert (response.status_code, urlsplit(response.headers["location"]).path) == (
        302,
        f"/tenant/{tenant.tenant_id}/login",
    )


def test_unauthenticated_json_request_gets_401_json(asgi_admin_client, tenant):
    response = asgi_admin_client.delete(f"/tenant/{tenant.tenant_id}/creative-agents/1/delete")
    assert (response.status_code, response.json()) == (401, {"error": "Authentication required"})
