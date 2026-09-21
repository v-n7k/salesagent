#!/usr/bin/env python3
"""
A2A Standard Endpoints Test - ACTUALLY WORKING VERSION

This replaces the skipped test_a2a_standard_endpoints.py with a version that actually runs.
The original was skipped because it tried to use python_a2a library, but we use a2a-sdk.

This test validates the actual HTTP endpoints that our A2A server exposes.
"""

import json
import os
import sys
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest
import requests
from a2a.types import CancelTaskRequest, GetTaskRequest, TaskNotFoundError
from adcp import get_adcp_spec_version

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.app import _AGENT_CARD_PATHS  # noqa: E402  (after the sys.path bootstrap above)
from src.core.tools.registry import TOOLS  # noqa: E402  (after the sys.path bootstrap above)
from tests.helpers.credentials import credential_headers

# Read the declared set from production: a path added to (or dropped from)
# `_AGENT_CARD_PATHS` must change what these tests grade. Sorted for a
# deterministic parametrization order.
AGENT_CARD_PATHS = sorted(_AGENT_CARD_PATHS)

# The one path the a2a-sdk factory mounts today — the regression guard.
CANONICAL_AGENT_CARD_PATH = "/.well-known/agent-card.json"


class TestA2AEndpointsActual:
    """Test actual A2A endpoints that we implement.

    The base URL arrives as the ``live_server`` fixture VALUE, not out of
    ``ADCP_SALES_PORT``. A process-global carries no sender (the fixture, the
    compose file and scripts/test-stack.sh all write that variable), no lifetime
    and no multiplicity, and its ``"8080"`` default silently aimed these tests at
    whatever happened to be listening there. Taking ``live_server`` also means the
    stack is guaranteed up, so a connection failure is a real failure instead of a
    skip — same rule as ``test_unknown_task_id_returns_task_not_found_code_on_the_wire``
    below.
    """

    @pytest.mark.integration
    def test_well_known_agent_json_endpoint_live(self, live_server):
        """Test /.well-known/agent-card.json endpoint against live server."""
        # a2a-sdk 1.0 canonical path is /.well-known/agent-card.json
        response = requests.get(f"{live_server['a2a']}/.well-known/agent-card.json", timeout=2)

        if response.status_code == 200:
            # Endpoint works - validate response
            assert response.headers["content-type"].startswith("application/json")

            data = response.json()
            assert "name" in data
            assert "description" in data
            assert "version" in data
            assert "skills" in data

            # a2a-sdk 1.0 (protobuf): URL is in supportedInterfaces, not top-level
            assert "supportedInterfaces" in data, "Agent card must have supportedInterfaces"
            interfaces = data["supportedInterfaces"]
            assert len(interfaces) > 0
            url = interfaces[0]["url"]

            # Critical regression test: URL should not have trailing slash
            assert not url.endswith("/"), f"Agent card URL should not have trailing slash: {url}"
            assert url.endswith("/a2a"), f"Agent card URL should end with '/a2a': {url}"

            # Should be Prebid Sales Agent
            assert data["name"] == "Prebid Sales Agent"

            # Should have skills
            assert "skills" in data
            assert len(data["skills"]) > 0

            # AdCP 2.5: Should have AdCP extension in capabilities
            assert "capabilities" in data
            assert "extensions" in data["capabilities"]
            extensions = data["capabilities"]["extensions"]
            assert len(extensions) > 0

            # Find AdCP extension
            adcp_ext = None
            for ext in extensions:
                if "adcp-extension" in ext.get("uri", ""):
                    adcp_ext = ext
                    break

            assert adcp_ext is not None, "AdCP extension not found in live agent card"
            assert adcp_ext["params"]["adcp_version"] == get_adcp_spec_version()
            assert "media_buy" in adcp_ext["params"]["protocols_supported"]

    @pytest.mark.integration
    def test_agent_json_endpoint_live(self, live_server):
        """Test /agent.json endpoint against live server."""
        response = requests.get(f"{live_server['a2a']}/agent.json", timeout=2)

        if response.status_code == 200:
            assert response.headers["content-type"].startswith("application/json")
            data = response.json()
            assert data["name"] == "Prebid Sales Agent"

            # Same URL validation as the well-known endpoint. a2a-sdk 1.0
            # (protobuf) puts the endpoint in supportedInterfaces, NOT top-level:
            # `data["url"]` here was a dormant 0.3-era read that never ran, because
            # /agent.json 404'd and this whole block sits behind a 200 check. Routing
            # the path woke it into a KeyError, which is what a vacuous assertion
            # does the moment it stops being vacuous.
            assert "supportedInterfaces" in data, "Agent card must have supportedInterfaces"
            interfaces = data["supportedInterfaces"]
            assert len(interfaces) > 0
            url = interfaces[0]["url"]

            assert not url.endswith("/"), f"Agent card URL should not have trailing slash: {url}"
            assert url.endswith("/a2a"), f"Agent card URL should end with '/a2a': {url}"

    @pytest.mark.integration
    def test_a2a_endpoint_accessible(self, live_server):
        """Test that /a2a endpoint is accessible (may require auth)."""
        # Test both /a2a and /a2a/ paths
        for path in ["/a2a", "/a2a/"]:
            response = requests.post(f"{live_server['a2a']}{path}", json={"test": "data"}, timeout=2)

            # Should not be 404 (endpoint exists)
            assert response.status_code != 404, f"Endpoint {path} should exist"

    @pytest.mark.integration
    def test_cors_headers_present(self, live_server):
        """Test that CORS headers are present for browser compatibility."""
        # CORS headers are only returned when the Origin matches an allowed origin.
        # Default ALLOWED_ORIGINS is "http://localhost:8000" — use that as Origin.
        allowed_origin = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",")[0].strip()

        # a2a-sdk 1.0 canonical path is /.well-known/agent-card.json
        response = requests.get(
            f"{live_server['a2a']}/.well-known/agent-card.json",
            headers={"Origin": allowed_origin},
            timeout=2,
        )

        if response.status_code == 200:
            # Should have CORS headers for an allowed origin
            assert "Access-Control-Allow-Origin" in response.headers, "Missing CORS headers"

    @pytest.mark.integration
    def test_options_preflight_support(self, live_server):
        """Test that OPTIONS requests work for CORS preflight."""
        # a2a-sdk 1.0 canonical path is /.well-known/agent-card.json
        response = requests.options(f"{live_server['a2a']}/.well-known/agent-card.json", timeout=2)

        # Should handle OPTIONS requests
        assert response.status_code in [200, 204], "OPTIONS request should be handled"


class TestAgentCardDiscoveryPathsLive:
    """Every declared agent-card path serves the same card on a LIVE server (#1440).

    The live server runs under lifespan, where `_install_admin_mounts()`
    re-appends the Flask catch-all `Mount("/")` last. That is the surface the
    in-process TestClient probe in
    tests/unit/test_a2a_transport_contract.py cannot reach: here a 200 also
    proves the card routes are matched BEFORE the catch-all, not swallowed by it.
    """

    @pytest.mark.integration
    @pytest.mark.parametrize("path", AGENT_CARD_PATHS)
    def test_declared_card_path_is_served_live(self, live_server, path):
        """GET on every path in _AGENT_CARD_PATHS returns 200 from the live server."""
        response = requests.get(f"{live_server['a2a']}{path}", timeout=2)

        assert response.status_code == 200, (
            f"{path} is declared in _AGENT_CARD_PATHS but the live server returned "
            f"{response.status_code}; every declared discovery path must be served"
        )
        assert response.headers["content-type"].startswith("application/json")

    @pytest.mark.integration
    def test_all_declared_card_paths_return_byte_identical_bodies_live(self, live_server):
        """The live server serves one byte-identical card on every declared path.

        Compares raw bytes, not the parsed dict: a caching fetcher keyed on bytes
        treats a re-serialization difference as a different document.
        """
        bodies = {path: requests.get(f"{live_server['a2a']}{path}", timeout=2) for path in AGENT_CARD_PATHS}

        for path, response in bodies.items():
            assert response.status_code == 200, f"{path} returned {response.status_code}, expected 200"

        canonical = bodies[CANONICAL_AGENT_CARD_PATH].content
        for path, response in bodies.items():
            assert response.content == canonical, (
                f"{path} body differs from {CANONICAL_AGENT_CARD_PATH}; "
                f"all declared paths must serve one byte-identical card"
            )

    @pytest.mark.integration
    @pytest.mark.parametrize("path", AGENT_CARD_PATHS)
    def test_host_derivation_applies_on_every_card_path_live(self, live_server, path):
        """Apx-Incoming-Host drives supportedInterfaces[0].url on every path.

        A path that returns 200 carrying the static fallback host is still broken:
        it advertises the wrong A2A endpoint to every tenant. That is the failure
        mode this grades, and the HOST is what discriminates it.

        The SCHEME is deliberately not pinned here. Whatever X-Forwarded-Proto a
        client sends, an edge proxy sets its own -- in-network our nginx terminates
        plain HTTP and forwards `http`, so pinning `https` asserts a value the
        deployment topology owns rather than anything the app decides. Trusting the
        edge's header IS the documented behaviour (src/app.py's get_protocol). The
        scheme logic is graded where the input is actually controllable, in
        tests/unit/test_agent_card_scheme.py; do not restore an https pin here.
        """
        response = requests.get(
            f"{live_server['a2a']}{path}",
            headers={"Apx-Incoming-Host": "tenant.example.com"},
            timeout=2,
        )

        assert response.status_code == 200, f"{path} returned {response.status_code}, expected 200"
        card = response.json()
        derived = urlparse(card["supportedInterfaces"][0]["url"])

        assert derived.netloc == "tenant.example.com", (
            f"{path} did not derive its URL from Apx-Incoming-Host: got {derived.geturl()!r}, "
            f"which means it served the static fallback host to a tenant"
        )
        assert derived.path == "/a2a", f"{path} derived the wrong endpoint path: {derived.geturl()!r}"
        assert derived.scheme in ("http", "https"), f"{path} derived a non-HTTP scheme: {derived.geturl()!r}"


class TestA2AAgentCardCreation:
    """Test agent card creation functions directly (no HTTP required)."""

    def test_create_agent_card_function(self):
        """Test the create_agent_card function directly."""
        try:
            from src.a2a_server.adcp_a2a_server import create_agent_card
        except ImportError as e:
            if e.name and e.name.startswith("a2a"):
                pytest.skip(f"a2a-sdk library not installed: {e}")
            raise

        agent_card = create_agent_card()

        # Validate structure (protobuf AgentCard fields)
        assert agent_card.name
        assert agent_card.description
        assert agent_card.version
        assert len(agent_card.skills) > 0
        assert len(agent_card.supported_interfaces) > 0

        # Validate content
        assert agent_card.name == "Prebid Sales Agent"

        # a2a-sdk 1.0: URL is in supported_interfaces[0].url, not agent_card.url
        interface_url = agent_card.supported_interfaces[0].url
        assert not interface_url.endswith("/"), f"Interface URL should not have trailing slash: {interface_url}"
        assert interface_url.endswith("/a2a"), f"Interface URL should end with '/a2a': {interface_url}"

        # Validate skills structure (protobuf: skills have id and description)
        for skill in agent_card.skills:
            assert skill.id
            assert skill.description

    def test_agent_card_adcp_extension(self):
        """Test that agent card includes AdCP 2.5 extension."""
        from src.a2a_server.adcp_a2a_server import create_agent_card

        agent_card = create_agent_card()

        # Check capabilities has extensions
        assert hasattr(agent_card, "capabilities")
        assert agent_card.capabilities is not None
        assert hasattr(agent_card.capabilities, "extensions")
        assert agent_card.capabilities.extensions is not None
        assert len(agent_card.capabilities.extensions) > 0

        # Find AdCP extension
        adcp_ext = None
        for ext in agent_card.capabilities.extensions:
            if "adcp-extension" in ext.uri:
                adcp_ext = ext
                break

        assert adcp_ext is not None, "AdCP extension not found in capabilities.extensions"

        # Validate AdCP extension structure
        adcp_version = get_adcp_spec_version()
        assert adcp_ext.uri == f"https://adcontextprotocol.org/schemas/{adcp_version}/protocols/adcp-extension.json"
        assert adcp_ext.params is not None
        # protobuf Struct: access fields dict-like
        params = adcp_ext.params
        assert "adcp_version" in params.fields
        assert "protocols_supported" in params.fields

        # Validate AdCP extension values
        assert params.fields["adcp_version"].string_value == adcp_version
        protocols_value = params.fields["protocols_supported"].list_value
        protocols = [v.string_value for v in protocols_value.values]
        assert len(protocols) >= 1
        # Currently only media_buy protocol is supported
        assert "media_buy" in protocols
        assert set(protocols) == {"media_buy"}, "Only media_buy protocol is currently supported"

    def test_agent_card_skills_coverage(self):
        """Test that agent card includes expected AdCP skills."""
        from src.a2a_server.adcp_a2a_server import create_agent_card

        agent_card = create_agent_card()
        skill_names = [skill.id for skill in agent_card.skills]

        # Should include core AdCP skills
        # Note: get_signals removed - should come from dedicated signals agents
        expected_skills = [
            "get_products",
            "create_media_buy",
            "sync_creatives",
            "list_creatives",
        ]

        for expected_skill in expected_skills:
            assert expected_skill in skill_names, f"Missing expected skill: {expected_skill}"

    def test_agent_card_serialization(self):
        """Test that agent card can be serialized to JSON."""
        from src.a2a_server.adcp_a2a_server import create_agent_card

        agent_card = create_agent_card()

        # Should be able to serialize to dict (protobuf: use MessageToDict)
        try:
            from google.protobuf.json_format import MessageToDict, MessageToJson

            card_dict = MessageToDict(agent_card)
            assert isinstance(card_dict, dict)

            # Should be JSON serializable
            json_str = MessageToJson(agent_card)
            assert len(json_str) > 0

            # Should be able to parse back
            parsed = json.loads(json_str)
            assert parsed["name"] == "Prebid Sales Agent"

        except Exception as e:
            pytest.fail(f"Agent card serialization failed: {e}")


class TestA2ARequestHandler:
    """Test the A2A request handler directly."""

    def setup_method(self):
        """Set up test fixtures."""
        from src.a2a_server.adcp_a2a_server import AdCPRequestHandler

        self.handler = AdCPRequestHandler()

    def test_handler_initialization(self):
        """Test that handler initializes correctly."""
        assert self.handler is not None
        assert hasattr(self.handler, "tasks")
        assert isinstance(self.handler.tasks, dict)

    def test_handler_has_required_methods(self):
        """Test that handler has all required A2A methods."""
        required_methods = [
            "on_message_send",
            "on_message_send_stream",
            "on_get_task",
            "on_cancel_task",
        ]

        for method_name in required_methods:
            assert hasattr(self.handler, method_name), f"Handler missing method: {method_name}"
            method = getattr(self.handler, method_name)
            assert callable(method), f"Method {method_name} is not callable"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "request_cls, method_name",
        [(GetTaskRequest, "on_get_task"), (CancelTaskRequest, "on_cancel_task")],
    )
    async def test_unknown_task_id_raises_task_not_found(self, request_cls, method_name):
        """An unknown task id raises TaskNotFoundError, not the generic internal
        error a bare None return produces — cancel is the same not-found condition
        as get, and both route through the shared ``_get_task_or_raise``.

        Fast smoke check on the raise only. It does NOT prove the wire code: the
        exception carries no code, and the client actually sees -32603 — see
        ``_get_task_or_raise`` (src/a2a_server/adcp_a2a_server.py) and #1670 for
        why, plus the xfail'd live-server test in TestA2AServerIntegration that
        grades the code on the wire. Assert on str(exc), not exc.code — there is
        none.

        Parametrized over both entry points so the shared assertion cannot drift
        between two byte-identical copies.

        Both halves of the raise are pinned: the human-readable message AND the
        structured ``data`` payload clients actually parse. Asserting the message
        alone would let ``data={"task_id": ...}`` be deleted with the suite still
        green, since the id appears in the message either way.
        """
        with pytest.raises(TaskNotFoundError) as exc:
            await getattr(self.handler, method_name)(request_cls(id="task_does_not_exist"), MagicMock())
        assert "task_does_not_exist" in str(exc.value)  # the requested id is surfaced
        assert exc.value.data == {"task_id": "task_does_not_exist"}  # ...and machine-readable

    def test_core_skills_are_dispatchable_over_a2a(self):
        """The core skills are dispatchable over A2A, per the registry.

        This used to assert one ``_handle_<tool>_skill`` method per tool. Those eleven
        methods are deleted: A2A dispatch is the single derived ``_dispatch_skill``,
        and a row is dispatchable because ``TOOLS[name].a2a`` is True. The old
        ``hasattr``-based selection was the defect it appeared to guard — it
        overrode the registry, advertising ``list_tasks``, ``get_task_status`` and
        ``complete_task`` on the agent card while answering MethodNotFoundError.
        """
        assert callable(self.handler._dispatch_skill), "A2A's one dispatch method is missing"

        # Note: get_signals removed - should come from dedicated signals agents
        for tool_name in ("get_products", "create_media_buy", "sync_creatives", "list_creatives"):
            assert TOOLS[tool_name].a2a is True, f"{tool_name} is not dispatchable over A2A"


class TestA2AServerIntegration:
    """Integration tests for complete A2A server setup."""

    @pytest.mark.integration
    @pytest.mark.parametrize("method", ["GetTask", "CancelTask"])
    def test_unknown_task_id_returns_task_not_found_code_on_the_wire(self, method, live_server):
        """The deliverable of the TaskNotFoundError change is what an A2A client
        SEES: JSON-RPC error code -32001. That code is not carried by the
        exception — it is synthesized downstream — so the direct-call test in
        TestA2ARequestHandler cannot prove it. This POSTs the real request to the
        running /a2a endpoint and grades the code on the wire.

        Uses the ``live_server`` fixture so the transport is guaranteed up: the
        base URL comes from ``live_server['a2a']`` and the assertion runs
        deterministically instead of skipping when nothing happens to be listening
        on the ad-hoc port — a skip under strict xfail is neither XFAIL nor XPASS,
        so the sole on-the-wire grade must never be allowed to no-op.

        Parametrized over both methods. `CancelTask` of an unknown id went from a silent
        None to an error, so it needs the same wire tripwire as `GetTask` — otherwise
        only half the contract is locked in.

        GRADUATED from a strict xfail against #1670. The code WAS -32603, because the
        v0.3 compat adapter ended in a bare `except Exception -> CoreInternalError` with
        no `A2AError -> code` mapping, flattening every raised error. With that adapter
        removed, requests dispatch through the SDK's own dispatcher, which performs the
        mapping: both methods now answer the spec's -32001. Measured before the xfail was
        deleted, not assumed from the marker going green.
        """
        response = requests.post(
            f"{live_server['a2a']}/a2a",
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": {"id": "task_does_not_exist"}},
            headers={"A2A-Version": "1.0"},
            timeout=5,
        )

        assert response.status_code == 200, f"JSON-RPC errors ride a 200 envelope: {response.status_code}"
        data = response.json()
        assert "error" in data, f"unknown task id must produce a JSON-RPC error: {data}"
        assert data["error"]["code"] == -32001, (
            f"A2A spec defines -32001 (TaskNotFoundError) for an unknown task id, got {data['error']['code']}"
        )

    @pytest.mark.integration
    def test_server_discovery_flow(self, live_server):
        """Test complete A2A client discovery flow."""
        # Step 1: Client discovers agent (a2a-sdk 1.0 canonical path)
        response = requests.get(f"{live_server['a2a']}/.well-known/agent-card.json", timeout=2)

        if response.status_code != 200:
            pytest.skip("A2A server not responding")

        agent_card = response.json()

        # Step 2: Validate agent card has what client needs
        assert "skills" in agent_card
        # a2a-sdk 1.0 (protobuf): URL is in supportedInterfaces, not top-level
        assert "supportedInterfaces" in agent_card

        # Step 3: Validate URL format for messaging
        url = agent_card["supportedInterfaces"][0]["url"]
        assert not url.endswith("/"), "URL should not have trailing slash (causes redirects)"

        # Step 4: Test that messaging endpoint exists
        messaging_url = url if url.endswith("/a2a") else f"{url}/a2a"

        # Try to connect (will fail with auth error, but should not be 404)
        response = requests.post(messaging_url, json={"test": "message"}, timeout=2)
        assert response.status_code != 404, "Messaging endpoint should exist"

    @pytest.mark.integration
    def test_authentication_flow(self, live_server):
        """Test authentication requirements."""
        # Should require Bearer token for messaging
        response = requests.post(
            f"{live_server['a2a']}/a2a",
            headers=credential_headers(token="invalid-token"),
            json={"method": "SendMessage", "params": {}},
            timeout=2,
        )

        # Should reject invalid token (401) not be 404
        assert response.status_code != 404, "Endpoint should exist"

        # Missing auth should also not be 404
        response = requests.post(f"{live_server['a2a']}/a2a", json={"method": "SendMessage", "params": {}}, timeout=2)
        assert response.status_code != 404, "Endpoint should exist even without auth"


def test_a2a_regression_summary():
    """Quick summary test for key regressions."""

    try:
        # Test 1: Agent card URL format
        from src.a2a_server.adcp_a2a_server import create_agent_card

        agent_card = create_agent_card()
        assert not agent_card.supported_interfaces[0].url.endswith("/"), "REGRESSION: Agent card URL has trailing slash"

        # Test 2: Handler can be created
        from src.a2a_server.adcp_a2a_server import AdCPRequestHandler

        handler = AdCPRequestHandler()
        assert handler is not None, "REGRESSION: Cannot create A2A handler"

        # Test 3: get_products is dispatchable over A2A and its row holds a plain callable
        # Note: signals tools removed - using get_products as core function check instead
        # (the module-level core_<tool>_tool wrappers are deleted; the registry row is
        # what invoke_tool calls and what decides A2A dispatchability)
        assert callable(TOOLS["get_products"].impl), "REGRESSION: registry impl not callable"
        assert TOOLS["get_products"].a2a is True, "REGRESSION: get_products not dispatchable over A2A"
    except ImportError as e:
        if e.name and e.name.startswith("a2a"):
            pytest.skip(f"a2a-sdk library not installed: {e}")
        raise

    print("✅ A2A regression tests passed")


if __name__ == "__main__":
    # Run basic checks when executed directly
    test_a2a_regression_summary()
