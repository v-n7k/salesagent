"""The agent service: what the creative-agent and signals-agent routes do (spec § 5.3).

A service function takes the tenant first, opens exactly one ``AgentUoW`` per call, reaches
the rows through the repository the kind names, and raises an ``AdminRefusal`` for what it
cannot do (a missing row is ``AdminNotFound``; a URL egress policy refuses is
``AdminInvalidInput``). It imports nothing from any web framework and catches nothing. The
kind record is data, not code: two routers, one function per operation.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.admin.errors import AdminNotFound
from src.admin.forms.agents import AgentFormBase, CreativeAgentForm, SignalsAgentForm
from src.admin.utils.url_policy import raise_if_url_blocked
from src.core.creative_agent_registry import CreativeAgentRegistry
from src.core.database.models import CreativeAgent, SignalsAgent
from src.core.database.repositories.uow import AgentUoW
from src.core.signals_agent_registry import SignalsAgentRegistry
from src.core.utils.operator_mcp import ProbeResult

_URL_LABEL = "Agent URL"


@dataclass(frozen=True)
class AgentKind:
    """Everything that differs between the two kinds of agent row."""

    key: str  # "creative" | "signals": the audit operation names are f"<op>_{key}_agent"
    label: str  # "Creative" | "Signals": the operator-facing sentences start with it
    repository: str  # the AgentUoW attribute holding the kind's repository
    model: type[CreativeAgent] | type[SignalsAgent]
    form: type[AgentFormBase]
    registry: Callable[[], Any]  # the registry CLASS, instantiated per probe so a test can patch probe_agent on it
    probe_fields: Callable[[ProbeResult], dict[str, Any]]  # a successful probe projected onto the template's keys


def _creative_probe_fields(probe: ProbeResult) -> dict[str, Any]:
    return {"message": probe.message, "format_count": probe.count, "sample_formats": list(probe.samples)}


def _signals_probe_fields(probe: ProbeResult) -> dict[str, Any]:
    return {"message": probe.message, "signal_count": probe.count}


CREATIVE = AgentKind(
    key="creative",
    label="Creative",
    repository="creative_agents",
    model=CreativeAgent,
    form=CreativeAgentForm,
    registry=CreativeAgentRegistry,
    probe_fields=_creative_probe_fields,
)

SIGNALS = AgentKind(
    key="signals",
    label="Signals",
    repository="signals_agents",
    model=SignalsAgent,
    form=SignalsAgentForm,
    registry=SignalsAgentRegistry,
    probe_fields=_signals_probe_fields,
)


def _fields(form: AgentFormBase) -> dict[str, Any]:
    """The form's fields by attribute read (not ``model_dump``: serialization happens at the edges)."""
    return {name: getattr(form, name) for name in type(form).model_fields}


def agent_repository(uow: AgentUoW, kind: AgentKind) -> Any:
    """The repository *uow* carries for *kind*; the router reads rows through the same one."""
    repository = getattr(uow, kind.repository)
    assert repository is not None
    return repository


def _existing(repository: Any, kind: AgentKind, agent_id: int) -> Any:
    row = repository.get(agent_id)
    if row is None:
        raise AdminNotFound(f"{kind.label} agent not found")
    return row


def create_agent(tenant_id: str, kind: AgentKind, form: AgentFormBase) -> str:
    """Store a new agent; returns the stored name."""
    raise_if_url_blocked(form.agent_url, _URL_LABEL)
    with AgentUoW(tenant_id) as uow:
        repository = agent_repository(uow, kind)
        row = repository.add(kind.model(tenant_id=tenant_id, **_fields(form)))
        return str(row.name)


def update_agent(tenant_id: str, kind: AgentKind, agent_id: int, form: AgentFormBase) -> str:
    """Overwrite an agent's fields from the form; a blank credential keeps the stored one."""
    with AgentUoW(tenant_id) as uow:
        row = _existing(agent_repository(uow, kind), kind, agent_id)
        raise_if_url_blocked(form.agent_url, _URL_LABEL)
        for name, value in _fields(form).items():
            if name == "auth_credentials" and value is None:
                continue
            setattr(row, name, value)
        return str(row.name)


def delete_agent(tenant_id: str, kind: AgentKind, agent_id: int) -> str:
    """Delete an agent; returns the deleted name."""
    with AgentUoW(tenant_id) as uow:
        repository = agent_repository(uow, kind)
        row = _existing(repository, kind, agent_id)
        repository.delete(row)
        return str(row.name)


def probe_agent(tenant_id: str, kind: AgentKind, agent_id: int) -> ProbeResult:
    """Dial the stored agent through its registry, after re-checking its URL against CURRENT policy.

    A row written while the egress-policy escape hatches were open must not become an outbound
    request once they are closed; the stored URL is asked again, at probe time.
    """
    with AgentUoW(tenant_id) as uow:
        row = _existing(agent_repository(uow, kind), kind, agent_id)
        raise_if_url_blocked(row.agent_url, _URL_LABEL)
        probe: ProbeResult = asyncio.run(kind.registry().probe_agent(row))
    return probe
