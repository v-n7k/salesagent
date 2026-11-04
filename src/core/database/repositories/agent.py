"""Tenant-scoped access to the operator-configured agent rows.

``creative_agents`` and ``signals_agents`` are the same shape of thing: rows an
operator registers per tenant, each with an ``enabled`` flag, read by a registry that
then calls out to them. Three sites asked the same question of them —
"the enabled agents of this tenant" — each with its own ``select()``, each importing
the model under an ALIAS (``CreativeAgent as CreativeAgentModel``), which is precisely
what the raw-select guard keys on model class names and therefore could not see.

The fix per CLAUDE.md pattern 3 is the repository, not a cleverer guard: with the query
here there is one tenant predicate rather than three remembered ones, and the aliased
import has nowhere left to live.

The admin surface reaches these rows through the same repositories (``AgentUoW``), so the
ten raw selects the two agent blueprints carried are gone with them: one generic base holds
the queries, and each kind declares only its model and its ordering.
"""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from src.core.database.models import CreativeAgent, SignalsAgent


class _AgentRepository[AgentRow: (CreativeAgent, SignalsAgent)]:
    """Tenant-scoped access to one kind of agent row; subclasses set ``_model`` and ``_ordering``.

    Every query keeps ``tenant_id == self._tenant_id`` in its WHERE clause: a row of another
    tenant is not found, not refused.

    Args:
        session: SQLAlchemy session (caller manages lifecycle).
        tenant_id: Tenant scope for all queries.
    """

    _model: ClassVar[type[CreativeAgent] | type[SignalsAgent]]
    _ordering: ClassVar[tuple[Any, ...]]

    def __init__(self, session: Session, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def _tenant_rows(self) -> Select[Any]:
        return select(self._model).where(self._model.tenant_id == self._tenant_id).order_by(*self._ordering)

    def get_enabled(self) -> list[AgentRow]:
        """This tenant's enabled agents, in the kind's own order.

        Ordered here rather than by each caller: the registry and the admin format-search
        endpoint both present agents in that order, and one of them was sorting in Python
        after the fact.
        """
        return list(self._session.scalars(self._tenant_rows().where(self._model.enabled.is_(True))).all())

    def list_all(self) -> list[AgentRow]:
        """Every agent of this tenant, enabled or not, in the kind's own order."""
        return list(self._session.scalars(self._tenant_rows()).all())

    def get(self, agent_id: int) -> AgentRow | None:
        """The agent *agent_id* of this tenant, or ``None``."""
        return self._session.scalars(self._tenant_rows().filter_by(id=agent_id)).first()

    def add(self, row: AgentRow) -> AgentRow:
        """Store *row* and flush, so its ``id`` is set on return."""
        self._session.add(row)
        self._session.flush()
        return row

    def delete(self, row: AgentRow) -> None:
        self._session.delete(row)


class CreativeAgentRepository(_AgentRepository[CreativeAgent]):
    """Tenant-scoped access for ``creative_agents``: highest priority (lowest number) first, then name."""

    _model = CreativeAgent
    _ordering = (CreativeAgent.priority, CreativeAgent.name)


class SignalsAgentRepository(_AgentRepository[SignalsAgent]):
    """Tenant-scoped access for ``signals_agents``: by name (the kind has no priority column)."""

    _model = SignalsAgent
    _ordering = (SignalsAgent.name,)
