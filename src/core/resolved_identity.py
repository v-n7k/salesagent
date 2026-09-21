"""Unified identity type for transport-agnostic business logic.

ResolvedIdentity is created at each transport boundary (MCP, A2A, REST) and
passed to _impl functions instead of transport-specific Context types.

This eliminates isinstance checks and auth extraction inside business logic.
"""

import logging
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Literal, overload

from adcp.types import AccountReference, AccountReferenceById
from pydantic import BaseModel, ConfigDict, InstanceOf

from src.core.schemas import Principal
from src.core.schemas.account import Account
from src.core.tenant_context import TenantContext

logger = logging.getLogger(__name__)


class TransportProtocol(StrEnum):
    """The transports a buyer can arrive on. THE declaration of what a transport is.

    A ``StrEnum``, so a call site cannot spell a transport as a bare string, and so a stored
    ``protocol`` column, an audit row and a wire payload all read the same value.
    ``tests/harness/transport.py``'s ``Transport`` takes its three core values from here; it adds
    the ``E2E_*`` members, which are test dispatch paths and not protocols a buyer can speak.

    It is a LABEL, never a decision. Nothing in ``src/`` branches on it, and it has exactly ONE
    consumer: scoping an observability record, so an operator reading the activity feed can see
    which surface a request arrived on. A response shape that varied by transport would be the
    thing this whole seam exists to prevent, so if a reader for this field is ever proposed,
    that is the question to ask first.
    """

    MCP = "mcp"
    A2A = "a2a"
    REST = "rest"


class PublicIdentity(BaseModel):
    """Whoever reached a PUBLIC tool: a resolved caller, or nobody.

    The resolver builds one for a registry row that does not require a credential
    (``get_products``, ``list_creative_formats``, ``get_adcp_capabilities``). A presented
    credential that resolves fills ``principal``; an absent one leaves it ``None``, and the
    tool branches on that itself. A presented credential that does NOT resolve never reaches
    the tool: the resolver refuses it with AUTH_INVALID on every row, public or protected.
    A protected tool never sees this type: it takes :class:`ResolvedIdentity`, whose fields
    are not optional.

    Immutable after creation; the identity does not change during request processing.
    """

    # ``extra="forbid"`` so a caller still passing ``principal_id=`` or ``tenant_id=`` fails at
    # construction instead of silently building an anonymous identity: both are derived.
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Both fields are ``InstanceOf``: an identity is BUILT from the resolved types, never
    # from a dict. Pydantic would otherwise coerce ``{"tenant_id": "d"}`` into a
    # TenantContext (``strict=True`` does not refuse a dict for a nested model), and that
    # coercion is how test code kept constructing identities from dicts after the type was
    # made one type. A dict now fails validation at construction.
    #
    # The principal the credential resolved to, built once from the row the lookup
    # selected. None for the anonymous caller.
    principal: InstanceOf[Principal] | None = None
    # The tenant the request names, its row loaded by the resolver. ONE type, never a
    # dict: the annotation used to be ``Any``, commented "TenantContext | dict | None
    # (transitional)", and that union is how dict-shaped tenant handling spread.
    tenant: InstanceOf[TenantContext] | None = None
    # No ``protocol`` field: the transport is a label the boundary holds for its own
    # observability record (``invoke_tool``'s parameter), and nothing read it off the
    # identity. A field with no reader on an identity built for stored-id work
    # (``identity_of``) could only claim a transport that never carried the request.
    #
    # No account either: an account is resolved for an authenticated caller only, so it
    # is a field of ``ResolvedIdentity``. Tenant-level billing policy (BR-RULE-059) and
    # account approval mode (BR-RULE-060) are NOT fields on the identity — they live on
    # identity.tenant (TenantContext).

    @property
    def principal_id(self) -> str | None:
        return self.principal.principal_id if self.principal is not None else None

    @property
    def tenant_id(self) -> str | None:
        return self.tenant.tenant_id if self.tenant is not None else None

    def replay_scope(self) -> tuple[str, str, str | None] | None:
        """``(tenant_id, principal_id, account_id)`` the idempotency cache keys on, or None.

        A caller that resolved no tenant or no principal has no scope to be cached under.
        Polymorphic rather than an ``isinstance`` at the boundary: the type that knows what
        it carries answers.
        """
        if self.tenant is None or self.principal is None:
            return None
        return self.tenant.tenant_id, self.principal.principal_id, None


class ResolvedIdentity(PublicIdentity):
    """The AUTHENTICATED caller of a protected tool. Principal and tenant are not optional.

    The type carries the boundary's decision. ``_resolve_identity`` refuses a missing
    credential (AUTH_MISSING) and a rejected one (AUTH_INVALID) before it can build this,
    so an implementation annotated ``identity: ResolvedIdentity`` reads
    ``identity.principal`` and ``identity.tenant`` directly: there is no ``None`` to check
    and no helper to call. The registry DERIVES a tool's credential policy from that
    annotation (``ToolSpec.requires_credential``), so the declaration and the guarantee are
    one thing. ``identity_of`` builds the same type from stored ids for server-initiated
    work.

    ``account`` is the account the REQUEST named, resolved by the resolver for this
    principal (``AccountRepository.find``): per request, never remembered on the
    principal, because one credential may access many accounts (core/account-ref.json).
    None when the request named none; a tool whose DTO requires an account takes
    :class:`AccountIdentity` instead and never sees the None.
    """

    principal: InstanceOf[Principal]
    tenant: InstanceOf[TenantContext]
    account: InstanceOf[Account] | None = None

    @property
    def principal_id(self) -> str:
        return self.principal.principal_id

    @property
    def tenant_id(self) -> str:
        return self.tenant.tenant_id

    def replay_scope(self) -> tuple[str, str, str | None]:
        return self.tenant_id, self.principal_id, self.account.account_id if self.account is not None else None


class AccountIdentity(ResolvedIdentity):
    """The authenticated caller of a tool whose request REQUIRES an account.

    ``create_media_buy``, ``update_media_buy`` and ``sync_creatives`` declare ``account``
    required on their DTOs, so the resolver has resolved one by the time they run and the
    field is not optional here. The registry checks the pairing at load: an implementation
    annotated with this type whose DTO does not require ``account`` is refused.
    """

    account: InstanceOf[Account]


from src.core.http_utils import get_header_case_insensitive as _get_header_case_insensitive


def _extract_auth_token(headers: Mapping[str, str]) -> str | None:
    """The Bearer value in ``Authorization``, or None when nothing was presented.

    ``Authorization: Bearer`` only. The ``x-adcp-auth`` alias is gone: pinned 3.1.1
    L2/authentication.mdx:71 says the credential MUST be carried in ``Authorization`` and
    that sellers MUST NOT require non-canonical aliases, and :153 says the alias is not
    recognized on the A2A surface at all. Accepting it was explicitly optional, so
    declining to is the compliant end state.

    A caller sending only the alias therefore presents nothing, which is the right reading:
    a protected tool answers AUTH_MISSING (nothing was presented to reject), never
    AUTH_INVALID.
    """
    authorization = _get_header_case_insensitive(headers, "Authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def _detect_tenant(headers: Mapping[str, str]) -> str | None:
    """The tenant_id this request names, by four header strategies. NO row is loaded.

    Identification only. The token check is scoped by tenant_id, so which tenant cannot be
    deferred; the row is loaded once by ``TenantContext.load`` after the tenant is known.

    Every strategy used to call a ``get_tenant_by_*`` helper ending in
    ``serialize_tenant_to_dict``, so identification loaded the entire row -- which
    ``resolve_identity`` then discarded, re-querying it on first field access. One indexed
    column per strategy instead.

    Strategy order, unchanged:
    1. Host header -> virtual host, then subdomain
    2. x-adcp-tenant header -> subdomain, then the literal id
    3. Apx-Incoming-Host -> virtual host
    4. localhost -> the "default" tenant
    """
    from src.core.config_loader import tenant_id_for

    host = _get_header_case_insensitive(headers, "host") or ""

    tenant_id = tenant_id_for(virtual_host=host)
    if not tenant_id and "." in host:
        subdomain = host.split(".")[0]
        if subdomain not in ["localhost", "adcp-sales-agent", "www", "admin"]:
            tenant_id = tenant_id_for(subdomain=subdomain)

    if not tenant_id:
        hint = _get_header_case_insensitive(headers, "x-adcp-tenant")
        if hint:
            # The hint is a subdomain when one matches, and otherwise taken as the id
            # itself -- unverified, exactly as before. An id that names no tenant fails
            # later, at the principal lookup that is scoped by it.
            tenant_id = tenant_id_for(subdomain=hint) or hint

    if not tenant_id:
        apx_host = _get_header_case_insensitive(headers, "apx-incoming-host")
        if apx_host:
            tenant_id = tenant_id_for(virtual_host=apx_host)

    if not tenant_id and host.split(":")[0] in ["localhost", "127.0.0.1", "localhost.localdomain"]:
        tenant_id = tenant_id_for(subdomain="default")

    return tenant_id


def _load_account(account_ref: AccountReference, tenant_id: str, principal: Principal) -> Account:
    """The account *account_ref* names for *principal*, as the schema object the identity carries.

    The resolver's fourth database read (after the tenant id, the tenant row and the
    principal row). It runs only for an authenticated caller -- the boundary requires a
    valid token whenever a request names an account -- so the access-scoped lookup in
    ``AccountRepository.find`` never sees an anonymous principal (#1417).
    """
    from src.core.database.repositories.account_lookup import find_account
    from src.core.database.repositories.account_serialization import account_from_row
    from src.core.database.repositories.uow import AccountUoW

    with AccountUoW(tenant_id) as uow:
        assert uow.accounts is not None
        return account_from_row(find_account(uow.accounts, account_ref, principal))


@overload
def _resolve_identity(
    headers: Mapping[str, str],
    *,
    require_valid_token: Literal[True],
    account_ref: AccountReference | None = None,
    credential_required_for: Callable[[TenantContext], bool] | None = None,
) -> ResolvedIdentity: ...


@overload
def _resolve_identity(
    headers: Mapping[str, str],
    *,
    require_valid_token: Literal[False],
    account_ref: AccountReference | None = None,
    credential_required_for: Callable[[TenantContext], bool] | None = None,
) -> PublicIdentity: ...


@overload
def _resolve_identity(
    headers: Mapping[str, str],
    *,
    require_valid_token: bool,
    account_ref: AccountReference | None = None,
    credential_required_for: Callable[[TenantContext], bool] | None = None,
) -> ResolvedIdentity | PublicIdentity: ...


def _resolve_identity(
    headers: Mapping[str, str],
    *,
    require_valid_token: bool,
    account_ref: AccountReference | None = None,
    credential_required_for: Callable[[TenantContext], bool] | None = None,
) -> ResolvedIdentity | PublicIdentity:
    """Resolve identity from request headers. PRIVATE to the boundary.

    Returns a :class:`ResolvedIdentity` when ``require_valid_token`` is True -- it has
    refused a missing or rejected credential by then, so principal and tenant are both
    present -- and a :class:`PublicIdentity` otherwise, whose principal may be ``None``.
    The overloads make that static: the boundary computes the flag from the row (the
    implementation's identity annotation, or the request naming an account -- a claim
    that needs a credential) and consumes the matching type with no ``isinstance``.

    ``credential_required_for`` is the row's tenant-dependent policy
    (``ToolSpec.requires_credential``), asked once the tenant row is loaded: a seller whose
    ``brand_manifest_policy`` is ``require_auth`` makes ``get_products``, a public tool,
    need a caller (BR-UC-001 INV-1). The refusal is minted HERE, the one minting site; the
    tool then receives a :class:`ResolvedIdentity`, which is a :class:`PublicIdentity`, with
    no branch of its own.

    When the request names an account (``account_ref``), it is resolved HERE, for the
    principal, so the identity is built once with the account inside (an
    :class:`AccountIdentity`). No identity is copied or amended afterwards.

    The leading underscore is the design, not a style choice. This is the ONE identity
    resolution in the tree and ``src/core/tools/_boundary.invoke_tool`` is its only caller;
    a transport that wanted to resolve its own has no public name to reach for. Four of them
    used to, and they disagreed twice -- A2A refusing a credential on a public task that MCP
    and REST served, and REST's discovery dependency hardcoding require_valid_token=False.
    ``ruff-boundary.toml`` bans importing it outside the boundary, so the privacy is enforced
    at lint time rather than by convention.

    It reads the headers ONCE and does everything identity-shaped: the Bearer value, the
    tenant, and the principal. No parameter accepts a pre-parsed token, so a second reader
    of the headers has nothing to feed into this one.

    Args:
        headers: The request headers, as the transport's framework exposes them.
        require_valid_token: The TOOL's declaration (``ToolSpec.requires_credential()``).
            If True, a missing credential raises. If False, a missing credential resolves
            anonymously (discovery). A PRESENTED credential that does not resolve raises
            either way.

    Returns:
        ResolvedIdentity with all fields resolved

    Raises:
        AdCPAuthRequiredError: No credential was presented and require_valid_token=True
            (AUTH_MISSING).
        AdCPAuthenticationError: A credential was presented and did not resolve
            (AUTH_INVALID), on every row: the pinned enum's MUST names no task.

    POSTCONDITION, relied on by every caller: when ``require_valid_token`` is True this
    either returns an identity with a resolved ``principal_id`` or raises. Callers do not
    need their own "no token" or "no principal" guards, and the ones that had them have
    been removed -- they were three transports answering one question three ways.

    Both errors are typed only. Rendering them as HTTP -- 401 and a ``WWW-Authenticate``
    challenge -- is the transport's job, in its own framework's terms.
    """
    # Import here to avoid circular dependency (auth_utils imports from database)
    from src.core.auth_utils import get_principal_from_token

    # Step 1: the Bearer value, parsed here and nowhere else.
    auth_token = _extract_auth_token(headers)

    # Step 2: NO credential presented, on a surface that requires one.
    #
    # AUTH_MISSING, not AUTH_INVALID: the v3.1.1 enum keys the split on whether a credential
    # was PRESENTED. Nothing was. A credential that is presented and fails to resolve is
    # AUTH_INVALID, raised in step 4.
    #
    # Before tenant detection, which is three DB lookups an anonymous caller has not earned.
    # Both transports that had this check ran it in this order for that reason; it is here
    # so that all of them get it, MCP included -- MCP had none, carried a principal-less
    # identity into the tool, and _impl code grew its own AdCPAuthRequiredError raises to
    # compensate.
    #
    # ``require_valid_token`` is the TOOL's declaration (``ToolSpec.auth``) travelling down
    # from the boundary, never a transport's own opinion. A discovery tool passes False and
    # still resolves anonymously.
    #
    # This function raises TYPED errors and knows nothing about HTTP. Turning AUTH_MISSING
    # into a 401 with a challenge is each transport's own job, done with its framework's
    # mechanism -- see the REST exception handler, the A2A route wrapper and the MCP
    # pre-dispatch gate. An earlier attempt had this function reach forward to the ASGI
    # response instead; it could not work, because MCP sends its response status before the
    # tool is ever dispatched.
    if require_valid_token and not auth_token:
        from src.core.exceptions import AdCPAuthRequiredError

        raise AdCPAuthRequiredError()

    # Step 3: the seller this request addresses, identified from the host and loaded. The
    # tenant comes first because a principal is a row in a tenant: a credential is only
    # ever verified inside the tenant the request reached, never looked up across tenants.
    tenant_id = _detect_tenant(headers)
    tenant: TenantContext | None = TenantContext.load(tenant_id) if tenant_id else None

    # Step 3b: the SELLER's policy. A public tool's row does not require a credential, but
    # the tenant it addresses may (brand_manifest_policy "require_auth" on get_products,
    # BR-UC-001 INV-1). The policy is seller data, so it can only be asked once the tenant
    # is loaded; the answer is the same AUTH_MISSING the row-level check mints above.
    if not require_valid_token and tenant is not None and credential_required_for is not None:
        require_valid_token = credential_required_for(tenant)
        if require_valid_token and not auth_token:
            from src.core.exceptions import AdCPAuthRequiredError

            raise AdCPAuthRequiredError()

    # Step 4: the token to its principal, inside that tenant. No tenant, no lookup.
    principal: Principal | None = None
    if auth_token and tenant is not None:
        principal = get_principal_from_token(auth_token, tenant.tenant_id)

    # Presented, and not a principal of the tenant addressed: AUTH_INVALID, on EVERY row.
    # The pinned enum (3.1/enums/error-code.json, AUTH_INVALID) keys the MUST on one thing --
    # "an `Authorization` header was present but verification failed" -- and names no task.
    # The public-task carve-out in compliance/3.1.1/universal/security.yaml is "return 200
    # WITHOUT credentials by design": it covers the absent credential, which step 2 already
    # let through, and says nothing about a presented one. A public tool used to take a
    # rejected credential as absent and serve the caller anonymously; the storyboard's own
    # narrative calls an agent that 200s a bad credential one that "is ignoring credentials
    # entirely". (No tenant means no lookup ran, which is the same outcome: nothing resolved.)
    if auth_token and principal is None:
        from src.core.exceptions import AdCPAuthenticationError

        raise AdCPAuthenticationError()

    # A public tool takes whoever arrived: a resolved caller, or -- with nothing presented
    # -- nobody.
    if not require_valid_token:
        return PublicIdentity(principal=principal, tenant=tenant)

    # A protected row: step 2 or 3b refused an absent credential and the check above refused
    # a rejected one, so both rows resolved. The assert is the static narrowing of that.
    assert tenant is not None and principal is not None

    if account_ref is None:
        return ResolvedIdentity(principal=principal, tenant=tenant)
    return AccountIdentity(
        principal=principal, tenant=tenant, account=_load_account(account_ref, tenant.tenant_id, principal)
    )


@overload
def identity_of(tenant_id: str, principal_id: str, account_id: None = None) -> ResolvedIdentity: ...


@overload
def identity_of(tenant_id: str, principal_id: str, account_id: str) -> AccountIdentity: ...


def identity_of(tenant_id: str, principal_id: str, account_id: str | None = None) -> ResolvedIdentity:
    """Resolution from STORED ids, for server-initiated work. Not for requests.

    A request is resolved by ``_resolve_identity``: the host names the tenant and the
    token names the principal inside it. Two jobs run with no request at all -- executing
    a media buy after a human approved it, and the delivery scheduler reporting on stored
    buys -- and they act on behalf of the row's owner, ON THE ROW'S ACCOUNT. The row
    carries the same facts the request path derives, as ``tenant_id``, ``principal_id``
    and ``account_id``, so this is the same resolution with those ids as its input: load
    the tenant, load the principal inside it, and, when the row names an account, load it
    through the same access-checked lookup a request goes through
    (:class:`AccountIdentity`); otherwise a :class:`ResolvedIdentity` with no account. It
    lives here because this module is the one place an identity is constructed. A row
    whose tenant or principal is missing is broken seller data, not an authentication
    outcome. Nothing is fabricated: an account is read off the row or not carried.
    """
    from src.core.auth_utils import get_principal_by_id
    from src.core.exceptions import AdCPConfigurationError

    tenant = TenantContext.load(tenant_id)
    if tenant is None:
        raise AdCPConfigurationError()
    principal = get_principal_by_id(tenant_id, principal_id)
    if principal is None:
        raise AdCPConfigurationError()
    if account_id is None:
        return ResolvedIdentity(principal=principal, tenant=tenant)
    account_ref = AccountReference(root=AccountReferenceById(account_id=account_id))
    return AccountIdentity(principal=principal, tenant=tenant, account=_load_account(account_ref, tenant_id, principal))
