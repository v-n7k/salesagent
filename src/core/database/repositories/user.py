"""Tenant-scoped access to the ``users`` rows the admin's tenant-access guard reads.

One predicate, moved here from the Flask decorator so the raw-select guard no longer needs
an allowlist row for it, and so the FastAPI guard asks the same question through the same
query.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.database.models import User


class UserRepository:
    """Tenant-scoped reads of ``users``.

    Args:
        session: SQLAlchemy session (caller manages lifecycle).
        tenant_id: Tenant scope for all queries.
    """

    def __init__(self, session: Session, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    def is_active_member(self, email: str) -> bool:
        """Whether *email* names an active user of this tenant."""
        stmt = select(User).filter_by(email=email.lower(), tenant_id=self._tenant_id, is_active=True)
        return self._session.scalars(stmt).first() is not None
