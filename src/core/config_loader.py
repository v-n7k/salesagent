"""Configuration loader for multi-tenant setup.

Environment variables:
    ADCP_MULTI_TENANT: Set to "true" to enable multi-tenant mode with subdomain routing.
    SALES_AGENT_DOMAIN: Required in multi-tenant mode (e.g., "sales-agent.example.com").
    SUPER_ADMIN_EMAILS: Comma-separated list of super admin emails.
    SUPER_ADMIN_DOMAINS: Comma-separated list of super admin email domains.
"""

import json
import logging
from typing import Any

from sqlalchemy import select

from src.core.config import get_settings
from src.core.database.database_session import get_db_session
from src.core.database.models import Tenant

logger = logging.getLogger(__name__)


def validate_multi_tenant_config() -> list[str]:
    """Validate configuration for multi-tenant mode.

    Returns:
        List of validation error messages, empty if valid.
    """
    errors = []

    if not is_single_tenant_mode():
        # Multi-tenant mode requires SALES_AGENT_DOMAIN
        if not get_settings().runtime.sales_agent_domain:
            errors.append("SALES_AGENT_DOMAIN is required for multi-tenant mode")

    return errors


def safe_json_loads(value, default=None):
    """Safely load JSON value that might already be deserialized (e.g. JSONB) or a JSON string."""
    if value is None:
        return default
    if isinstance(value, list | dict):
        # Already deserialized (JSONB column)
        return value
    if isinstance(value, str):
        # JSON string
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def get_default_tenant() -> dict[str, Any] | None:
    """Get the default tenant for CLI/testing."""
    try:
        with get_db_session() as db_session:
            # Get first active tenant or specific default
            # Try to get 'default' tenant first, fall back to first active tenant
            stmt = select(Tenant).filter_by(tenant_id="default", is_active=True)
            tenant = db_session.scalars(stmt).first()

            if not tenant:
                # Fall back to first active tenant by creation date
                stmt = select(Tenant).filter_by(is_active=True).order_by(Tenant.created_at)
                tenant = db_session.scalars(stmt).first()

            if tenant:
                from src.core.utils.tenant_utils import serialize_tenant_to_dict

                return serialize_tenant_to_dict(tenant)
            return None
    except Exception as e:
        # If table doesn't exist or other DB errors, return None
        if "no such table" in str(e) or "does not exist" in str(e):
            return None
        raise


def get_tenant_by_subdomain(subdomain: str) -> dict[str, Any] | None:
    """Get tenant by subdomain.

    Args:
        subdomain: The subdomain to look up (e.g., 'wonderstruck' from wonderstruck.sales-agent.example.com)

    Returns:
        Tenant dict if found, None otherwise
    """
    try:
        with get_db_session() as db_session:
            stmt = select(Tenant).filter_by(subdomain=subdomain, is_active=True)
            tenant = db_session.scalars(stmt).first()

            if tenant:
                from src.core.utils.tenant_utils import serialize_tenant_to_dict

                return serialize_tenant_to_dict(tenant)
            return None
    except Exception as e:
        # If table doesn't exist or other DB errors, return None
        if "no such table" in str(e) or "does not exist" in str(e):
            return None
        raise


def get_tenant_by_id(tenant_id: str) -> dict[str, Any] | None:
    """Get tenant by tenant_id.

    Args:
        tenant_id: The tenant_id to look up (e.g., 'tenant_wonderstruck')

    Returns:
        Tenant dict if found, None otherwise
    """
    try:
        with get_db_session() as db_session:
            stmt = select(Tenant).filter_by(tenant_id=tenant_id, is_active=True)
            tenant = db_session.scalars(stmt).first()

            if tenant:
                from src.core.utils.tenant_utils import serialize_tenant_to_dict

                return serialize_tenant_to_dict(tenant)
            return None
    except Exception as e:
        # If table doesn't exist or other DB errors, return None
        if "no such table" in str(e) or "does not exist" in str(e):
            return None
        raise


def get_tenant_by_virtual_host(virtual_host: str) -> dict[str, Any] | None:
    """Get tenant by virtual host."""
    try:
        with get_db_session() as db_session:
            stmt = select(Tenant).filter_by(virtual_host=virtual_host, is_active=True)
            tenant = db_session.scalars(stmt).first()

            if tenant:
                from src.core.utils.tenant_utils import serialize_tenant_to_dict

                return serialize_tenant_to_dict(tenant)
            return None
    except Exception as e:
        # If table doesn't exist or other DB errors, return None
        if "no such table" in str(e) or "does not exist" in str(e):
            return None
        raise


def tenant_id_for(*, virtual_host: str | None = None, subdomain: str | None = None) -> str | None:
    """The tenant_id matching a host or subdomain, WITHOUT loading the tenant row.

    Identification, not hydration. The token check is scoped by tenant_id
    (``get_principal_from_token(auth_token, tenant_id)``), so knowing WHICH tenant cannot be
    deferred; the row itself is loaded once by ``TenantContext.load`` after the tenant is
    known.

    Its siblings ``get_tenant_by_virtual_host`` / ``get_tenant_by_subdomain`` end in
    ``serialize_tenant_to_dict`` and hand back the whole row, so identification paid for
    hydration on every request and the identity then DISCARDED that row and re-queried it on
    first field access. This selects one indexed column instead.
    """
    if not (virtual_host or subdomain):
        return None
    try:
        with get_db_session() as db_session:
            filters: dict[str, str] = {"virtual_host": virtual_host} if virtual_host else {"subdomain": subdomain or ""}
            stmt = select(Tenant.tenant_id).filter_by(is_active=True, **filters)
            return db_session.scalars(stmt).first()
    except Exception as e:
        if "no such table" in str(e) or "does not exist" in str(e):
            return None
        raise


def is_single_tenant_mode() -> bool:
    """Single-tenant mode is the default; multi-tenant is ``ADCP_MULTI_TENANT=true``."""
    return get_settings().runtime.is_single_tenant


def ensure_default_tenant_exists() -> dict[str, Any] | None:
    """Ensure a default tenant exists for single-tenant deployments.

    In single-tenant mode, this creates a default tenant if none exists.
    This should be called after database migrations complete.

    Returns:
        The default tenant dict if created/exists, None if in multi-tenant mode
    """
    if not is_single_tenant_mode():
        logger.debug("Multi-tenant mode enabled, skipping default tenant creation")
        return None

    try:
        with get_db_session() as db_session:
            # Check if any tenant exists
            stmt = select(Tenant).filter_by(is_active=True)
            existing = db_session.scalars(stmt).first()

            if existing:
                logger.debug(f"Tenant already exists: {existing.name}")
                from src.core.utils.tenant_utils import serialize_tenant_to_dict

                return serialize_tenant_to_dict(existing)

            # Create default tenant for single-tenant deployments
            logger.info("Single-tenant mode: Creating default tenant...")

            # The super admins are the initial authorization
            authorized_emails = get_settings().auth.super_admin_email_list
            authorized_domains = get_settings().auth.super_admin_domain_list

            from datetime import UTC, datetime

            now = datetime.now(UTC)
            default_tenant = Tenant(
                tenant_id="default",
                name="Default Publisher",
                subdomain="default",  # Required field for routing
                ad_server="mock",  # Start with mock adapter, user can configure later
                authorized_emails=authorized_emails,
                authorized_domains=authorized_domains,
                is_active=True,
                created_at=now,
                updated_at=now,
            )

            db_session.add(default_tenant)
            db_session.commit()
            db_session.refresh(default_tenant)

            logger.info(f"Created default tenant: {default_tenant.name} (id: {default_tenant.tenant_id})")

            from src.core.utils.tenant_utils import serialize_tenant_to_dict

            return serialize_tenant_to_dict(default_tenant)

    except Exception as e:
        # Don't fail startup if tenant creation fails - log and continue
        logger.warning(f"Could not ensure default tenant exists: {e}")
        return None


def get_single_tenant() -> dict[str, Any] | None:
    """Get the single tenant for single-tenant deployments.

    In single-tenant mode, returns the only active tenant.
    In multi-tenant mode, returns None.

    Returns:
        The single tenant dict, or None if multi-tenant mode or no tenant exists
    """
    if not is_single_tenant_mode():
        return None

    return get_default_tenant()
