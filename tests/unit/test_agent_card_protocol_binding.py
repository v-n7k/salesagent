"""Every advertised A2A interface must declare its protocol binding.

WHY. An A2A 1.x client selects the interface it will talk to by matching the binding:
``i.protocolBinding?.toUpperCase() === "JSONRPC"`` (``@a2a-js/sdk``,
``client/transports/pick_interface.ts``). The optional chaining means an interface that
omits the field does not raise — it simply matches NOTHING, the client finds no usable
interface, and it reports the agent UNREACHABLE without ever sending a request.

Measured: with the field absent, ``@adcp/sdk 14.0.0-rc.35``'s storyboard runner graded
ZERO checks against this agent and reported ``overall_status: unreachable``; declaring it
took the same runner to 72 storyboards executed. So this is not cosmetic card polish —
its absence makes the A2A surface unreachable to any 1.x buyer, while leaving the 0.3
clients that ignore the field working, which is why nothing else noticed.

Both construction paths are covered. ``create_agent_card`` builds the static card, and
``_card_with_url`` copies it and overwrites only the URL for the per-request dynamic card
— a copy that dropped the binding would leave the served card broken while the static one
looked correct.
"""

from __future__ import annotations

from src.a2a_server.adcp_a2a_server import create_agent_card
from src.app import _card_with_url

#: What the client uppercases and compares against. Spelled here rather than imported
#: from production, so a change to the emitted value fails this test instead of agreeing
#: with itself.
_JSONRPC = "JSONRPC"


def test_static_card_declares_a_binding_on_every_interface() -> None:
    card = create_agent_card()

    assert card.supported_interfaces, "the card advertises no interfaces at all"
    for iface in card.supported_interfaces:
        assert iface.protocol_binding, (
            f"interface {iface.url!r} declares no protocol_binding, so an A2A 1.x client "
            "matches no interface and reports this agent unreachable"
        )
        assert iface.protocol_binding.upper() == _JSONRPC, (
            f"interface {iface.url!r} advertises binding {iface.protocol_binding!r}; this "
            f"agent serves JSON-RPC at that URL, so a 1.x client looking for {_JSONRPC} "
            "will not match it"
        )


def test_the_dynamic_card_keeps_the_binding_when_it_rewrites_the_url() -> None:
    """``_card_with_url`` is what a real request gets — it must not drop the binding."""
    rewritten = _card_with_url("https://seller.example.com/a2a")

    assert rewritten.supported_interfaces, "the dynamic card advertises no interfaces"
    assert rewritten.supported_interfaces[0].url == "https://seller.example.com/a2a"
    assert rewritten.supported_interfaces[0].protocol_binding.upper() == _JSONRPC, (
        "the per-request card lost its protocol_binding while rewriting the URL"
    )
