"""The proof-of-control challenge goes out through the egress seam, not a raw client.

salesagent-prkv.71: this service called ``httpx.AsyncClient`` directly, which the
TID251 bans in ``ruff-egress.toml`` forbid across ``src/``. The lint proves the
import is gone; these prove the REQUEST actually goes through ``asend`` and that
the seam's two failure modes still produce the fail-closed answer.

Worth a behavioural test rather than trusting the lint: the BDD harness replaces
``get_notification_proof_service`` wholesale, so no existing test reaches this
code path at all — the lint could pass while the call did the wrong thing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from adcp.types import NotificationConfig

from src.core.security.egress.policy import OutboundRequestBlocked
from src.services.notification_proof_service import NotificationProofService


def _config(url: str = "https://buyer.adcp-partner.com/proof") -> NotificationConfig:
    # NOT a .test/.example host: those are RFC 2606 reserved TLDs that the service
    # refuses deterministically BEFORE it dials, so a reserved-TLD url would make
    # every case below pass for the wrong reason.
    return NotificationConfig(url=url, subscriber_id="sub-1", event_types=["final"])


async def _prove_with(side_effect=None, http_status: int = 200) -> tuple[bool, AsyncMock]:
    send = AsyncMock()
    if side_effect is not None:
        send.side_effect = side_effect
    else:
        send.return_value.http_status = http_status
    with patch("src.services.notification_proof_service.asend", send):
        proven = await NotificationProofService().prove("acct-1", _config())
    return proven, send


@pytest.mark.asyncio
async def test_challenge_is_sent_through_the_seam():
    """The seam is called, with the challenge body and a single attempt."""
    proven, send = await _prove_with()

    assert proven is True
    assert send.await_count == 1
    _args, kwargs = send.await_args
    assert kwargs["json"] == {
        "type": "adcp.notification.proof_of_control",
        "account_id": "acct-1",
        "subscriber_id": "sub-1",
    }
    # One attempt: this runs inside the buyer's request cycle, so a retry only
    # spends latency the caller budgeted. A default max_attempts would silently
    # triple the worst case.
    assert kwargs["max_attempts"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 404, 500])
async def test_a_non_2xx_challenge_is_not_proven(status):
    proven, _ = await _prove_with(http_status=status)
    assert proven is False


@pytest.mark.asyncio
async def test_an_egress_refusal_is_not_proven():
    """The seam owns the address decision; its refusal is fail-closed, not an error."""
    proven, _ = await _prove_with(side_effect=OutboundRequestBlocked())
    assert proven is False


@pytest.mark.asyncio
async def test_a_transport_failure_is_not_proven():
    proven, _ = await _prove_with(side_effect=TimeoutError("timed out"))
    assert proven is False
