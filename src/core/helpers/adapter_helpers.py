"""Adapter instance creation and configuration helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.adapters import AdServerAdapter
    from src.core.database.models import Tenant as DBTenant
    from src.core.resolved_identity import ResolvedIdentity
    from src.core.tenant_context import TenantContext

    #: Same shape as ResolvedIdentity.tenant (src/core/resolved_identity.py): the tenant
    #: context the resolver loaded. Never a dict.
    IdentityTenant = TenantContext
    #: IdentityTenant plus the raw ORM row some call sites pass directly (e.g.
    #: media_buy_create.py's session.scalars(...).first()) instead of routing
    #: through identity.tenant.
    TenantLike = DBTenant | IdentityTenant


from src.adapters.google_ad_manager import GoogleAdManager
from src.adapters.kevel import Kevel
from src.adapters.mock_ad_server import MockAdServer as MockAdServerAdapter
from src.adapters.triton_digital import TritonDigital

logger = logging.getLogger(__name__)


# ``build_agent_config`` and its ``_HasAgentFields`` Protocol used to sit here.
# salesagent-4n88 (#1802) deleted them: both registries that built an adcp
# ``AgentConfig`` for ``ADCPMultiAgentClient`` now dial the guarded MCP seam
# (``src.core.utils.operator_mcp.call_operator_mcp_tool``), so nothing
# constructs one any more. Keeping a second, unreachable way to build agent
# auth would be the duplication the CLAUDE.md DRY invariant forbids.
#
# ``raise_mapped_adcp_error`` went with them, one release late. This comment used to
# exempt it -- "the registries still catch the SDK's own ADCPError and delegate the
# mapping here" -- and that was false in three places at once: neither registry catches
# ``ADCPError`` or imports this module, the function's own docstring named two callers that
# did not exist, and ``outbound_error_mapping.py`` already described it as deleted while it
# was still here. ``raise_mapped_outbound_error`` is what the registries actually call
# (``creative_agent_registry.py:525``). It was also the second of the two raise sites
# passing a plain dict as ``details``, which no longer constructs.


def _resolve_tenant_id_and_fallback_adapter(tenant: TenantLike) -> tuple[str, str]:
    """Extract tenant_id and the tenant.ad_server fallback adapter type.

    Takes the ORM model (Tenant) or the TenantContext off the identity; both carry the
    two columns. This is the pre-AdapterConfig fallback only — callers needing the
    authoritative adapter type must go through ``resolve_tenant_adapter_type``.
    """
    return tenant.tenant_id, tenant.ad_server or "mock"


def resolve_tenant_adapter_type(tenant: TenantLike) -> str:
    """Resolve the authoritative ad-server adapter type for a tenant.

    Single source of truth for adapter-TYPE resolution: ``AdapterConfig.adapter_type``
    (via ``AdapterConfigRepository``) wins when a row exists, falling back to
    ``tenant.ad_server``/``tenant["ad_server"]`` otherwise. ``get_adapter()`` and the
    principal-free ``get_adapter_class_for_tenant()`` read path both route through
    this function so the two can never diverge (salesagent-dn2s: divergent
    tenant-adapter-type resolution copies would only half-close INV-4).

    Args:
        tenant: Tenant context (dict or ORM model).
    """
    logger = logging.getLogger(__name__)

    resolved_tenant = tenant
    tenant_id, selected_adapter = _resolve_tenant_id_and_fallback_adapter(resolved_tenant)
    logger.info(f"[ADAPTER_SELECT] Initial selected_adapter from tenant.ad_server: {selected_adapter}")

    from src.core.database.repositories.adapter_config import read_adapter_config

    config_row = read_adapter_config(tenant_id)
    if config_row and config_row.adapter_type:
        selected_adapter = config_row.adapter_type
        logger.info(f"[ADAPTER_SELECT] Using AdapterConfig.adapter_type: {selected_adapter}")

    return selected_adapter or "mock"


@dataclass(frozen=True)
class AdapterContext:
    """Who the tenant is and which adapter answers for it — resolved once.

    Every adapter-facing helper needs the same three facts, and each used to
    re-derive them inline. That is not merely repetitive: the steps must agree,
    because ``adapter_type`` selects the class while ``tenant_id`` selects the
    config row, and two helpers resolving differently would read one tenant's
    column while acting as another's adapter.
    """

    tenant: DBTenant | IdentityTenant
    adapter_type: str
    tenant_id: str


def resolve_adapter_context(tenant: TenantLike) -> AdapterContext:
    """The ONE resolve every adapter helper starts from (#1721 Lane B, step 4.1)."""
    resolved_tenant = tenant
    adapter_type = resolve_tenant_adapter_type(resolved_tenant)
    tenant_id, _ = _resolve_tenant_id_and_fallback_adapter(resolved_tenant)
    return AdapterContext(tenant=resolved_tenant, adapter_type=adapter_type, tenant_id=tenant_id)


def get_adapter_class_for_tenant(tenant: TenantLike) -> type[AdServerAdapter]:
    """Resolve the ad-server adapter CLASS for a tenant, without a Principal.

    For read-only capability/discovery paths (e.g. get_adcp_capabilities) that
    only need adapter-level CLASS attributes (default_channels,
    get_targeting_capabilities) and must work identically for anonymous and
    authenticated callers per AdCP INV-4 (capabilities describe the seller,
    not the caller). Deliberately bypasses ``Adapter.__init__`` — Kevel and
    TritonDigital unconditionally require a principal-bound config in
    ``__init__`` and would crash for a synthetic/tenant-only Principal.

    Raises when the tenant's mock-adapter ``test_behavior["unavailable"]``
    fault-injection flag is set (salesagent-689e) — deliberately pinned here,
    not in ``resolve_tenant_adapter_type()``, because that function also backs
    ``get_adapter()``/the real media-buy path for the same tenant; raising
    there would leak the fault onto ``create_media_buy`` during an e2e run.

    Args:
        tenant: Tenant context (dict or ORM model).
    """
    from src.adapters import get_adapter_class

    return get_adapter_class(resolve_adapter_context(tenant).adapter_type)


#: Resolved adapter type -> the AdapterConfig column backing its manual-approval
#: requirement. Triton has no such column (not modeled), so it is absent here.
_MANUAL_APPROVAL_COLUMNS: dict[str, str] = {
    "google_ad_manager": "gam_manual_approval_required",
    "kevel": "kevel_manual_approval_required",
    "mock": "mock_manual_approval_required",
}


def resolve_manual_approval_signal(tenant: IdentityTenant) -> bool:
    """Whether this tenant's configuration genuinely requires manual approval
    on new media buys -- the same signal ``_create_media_buy_impl`` enforces
    (media_buy_create.py), read tenant/DB-side so it works without a live
    adapter instance (capabilities.py only holds the adapter CLASS, per INV-4 /
    salesagent-dn2s -- ``manual_approval_required`` is an instance attribute
    set in ``Adapter.__init__`` and does not exist on the class).

    ``tenant.human_review_required`` is NOT NULL DEFAULT TRUE at the schema
    level (a real, always-present tenant setting, not a Python-level default
    papering over a missing key) -- reading it directly is an honest claim
    about real enforced behavior, not an invented default (salesagent-rldj/
    salesagent-y9ld Core Invariant). Falls back to the resolved adapter type's
    own manual-approval DB column; that column is nullable and this reader
    applies NO default when it is unset -- deliberately NOT the same
    True-when-null policy ``get_adapter()``'s live adapter_config assembly
    uses for enforcement, since that default is exactly the false-conformance
    risk this reader must avoid (salesagent-becl.72 refine).
    """
    if tenant.human_review_required:
        return True

    ctx = resolve_adapter_context(tenant)
    column = _MANUAL_APPROVAL_COLUMNS.get(ctx.adapter_type)
    if not column:
        return False

    tenant_id = ctx.tenant_id

    from src.core.database.repositories.adapter_config import read_adapter_config

    row = read_adapter_config(tenant_id)
    return bool(row and getattr(row, column, None) is True)


def get_adapter(identity: ResolvedIdentity) -> MockAdServerAdapter | GoogleAdManager | Kevel | TritonDigital:
    """The ad-server adapter that acts for *identity*.

    The tenant decides which ad server answers and with what configuration; the
    principal is the buyer inside it. Both come off the one identity, resolved from a
    request or from stored ids, so they cannot be handed over as a mismatched pair.
    """
    principal = identity.principal
    tenant = identity.tenant
    ctx = resolve_adapter_context(tenant)
    selected_adapter = ctx.adapter_type
    tenant_id = ctx.tenant_id

    # Get adapter config via repository
    from src.core.database.repositories.adapter_config import AdapterConfigRepository, read_adapter_config

    targeting_config: dict[str, object] | None = None
    naming_templates: tuple[str | None, str | None] | None = None

    config_row = read_adapter_config(tenant_id)

    adapter_config: dict[str, object] = {"enabled": True}
    if config_row:
        adapter_type = config_row.adapter_type
        logger.info(f"[ADAPTER_SELECT] adapter_type from AdapterConfig: {adapter_type}")
        if adapter_type == "mock":
            # Default to True (require approval) for safety
            adapter_config["manual_approval_required"] = (
                config_row.mock_manual_approval_required
                if config_row.mock_manual_approval_required is not None
                else True
            )
        elif adapter_type == "google_ad_manager":
            adapter_config = AdapterConfigRepository.get_gam_config(config_row)
            targeting_config = AdapterConfigRepository.get_gam_targeting_config(config_row)
            naming_templates = AdapterConfigRepository.get_gam_naming_templates(config_row)

            # Get advertiser_id from principal's platform_mappings (per-principal, not tenant-level)
            # Support both old format (nested under "google_ad_manager") and new format (root "gam_advertiser_id")
            advertiser_id: str | None = None
            if principal.platform_mappings:
                # Try nested format first
                gam_mappings = principal.platform_mappings.get("google_ad_manager", {})
                advertiser_id = gam_mappings.get("advertiser_id")
                logger.info(
                    f"[ADAPTER_CONFIG] principal_id={principal.principal_id}, platform_mappings={principal.platform_mappings}, gam_mappings={gam_mappings}, advertiser_id={advertiser_id}"
                )

                # Fall back to root-level format if nested not found
                if not advertiser_id:
                    advertiser_id = principal.platform_mappings.get("gam_advertiser_id")
                    logger.info(f"[ADAPTER_CONFIG] Fell back to root-level gam_advertiser_id: {advertiser_id}")

                adapter_config["company_id"] = advertiser_id
                logger.info(f"[ADAPTER_CONFIG] Set adapter_config['company_id']={advertiser_id}")
            else:
                adapter_config["company_id"] = None
                logger.info("[ADAPTER_CONFIG] principal.platform_mappings is None/empty, set company_id=None")
        elif adapter_type == "kevel":
            adapter_config["network_id"] = config_row.kevel_network_id or ""
            adapter_config["api_key"] = config_row.kevel_api_key or ""
            # Default to True (require approval) for safety
            adapter_config["manual_approval_required"] = (
                config_row.kevel_manual_approval_required
                if config_row.kevel_manual_approval_required is not None
                else True
            )
        elif adapter_type == "triton":
            adapter_config["station_id"] = config_row.triton_station_id or ""
            adapter_config["api_key"] = config_row.triton_api_key or ""

    if not selected_adapter:
        # Default to mock if no adapter specified
        selected_adapter = "mock"
        if not adapter_config:
            adapter_config = {"enabled": True}

    logger.info(f"[ADAPTER_SELECT] FINAL selected_adapter: {selected_adapter}")
    if selected_adapter == "mock":
        logger.info("[ADAPTER_SELECT] Instantiating MockAdServerAdapter")
        return MockAdServerAdapter(adapter_config, principal, tenant_id=tenant_id)
    elif selected_adapter == "google_ad_manager":
        # network_code is required for GoogleAdManager
        network_code = adapter_config.get("network_code")
        if not network_code or not isinstance(network_code, str):
            raise ValueError("network_code is required for GoogleAdManager adapter")

        company_id = adapter_config.get("company_id")
        advertiser_id = company_id if isinstance(company_id, str) else None
        trafficker_id_val = adapter_config.get("trafficker_id")
        trafficker_id = trafficker_id_val if isinstance(trafficker_id_val, str) else None

        logger.info("[ADAPTER_SELECT] Instantiating GoogleAdManager")
        logger.info(
            f"[ADAPTER_SELECT] GAM params: network_code={network_code}, advertiser_id={advertiser_id}, trafficker_id={trafficker_id}"
        )
        return GoogleAdManager(
            adapter_config,
            principal,
            network_code=network_code,
            advertiser_id=advertiser_id,
            trafficker_id=trafficker_id,
            tenant_id=tenant_id,
            targeting_config=targeting_config,
            naming_templates=naming_templates,
        )
    elif selected_adapter == "kevel":
        return Kevel(adapter_config, principal, tenant_id=tenant_id)
    elif selected_adapter in ["triton", "triton_digital"]:
        return TritonDigital(adapter_config, principal, tenant_id=tenant_id)
    else:
        # Default to mock for unsupported adapters
        return MockAdServerAdapter(adapter_config, principal, tenant_id=tenant_id)
