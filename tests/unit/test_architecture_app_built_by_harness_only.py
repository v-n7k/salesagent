"""Guard: the app and its test clients are built by the harness and nowhere else.

A test takes its app and its client from the harness: the ``admin_client`` fixture,
``env.get_rest_client()``, or ``tests/helpers/admin_session.admin_test_app()``. The two
``admin_client`` fixture bodies, in ``tests/admin/conftest.py`` and ``tests/integration/conftest.py``,
still build their app and client themselves, so they are rows (#2536) until that app is built
under ``tests/harness/`` by a planned ``AdminEnv``; the exemption is not widened to cover them. A
test module that calls ``create_app(...)``, ``Flask(...)``, ``FastAPI(...)``, ``TestClient(...)``
or ``app.test_client()`` builds a second app. The harness does not configure that app, so a patch
that the harness applies misses it.

The scan reads the AST of every module under ``tests/`` except ``tests/harness/`` and
``tests/helpers/``, where the harness and its shared helpers build the apps. It flags a call to a
name in ``APP_CONSTRUCTORS``, bare or as an attribute (``admin.create_app(...)``), and a call to
the ``test_client`` method. A string that mentions ``create_app()`` is not a call. Rows are keyed
``(path, enclosing function)``, because a line number goes stale on any edit above the call. One
row covers every construction in a function.

``KNOWN_APP_CONSTRUCTIONS`` lists each function, or module body, outside the harness that built an
app or a client when this guard landed (#2536). It only shrinks, and every row carries
``# FIXME(#2536)``. A test that needs an app or a client takes it from the harness and adds no row.

To leave the list, replace the construction with the fixture, ``env.get_rest_client()`` or
``admin_test_app()``, and delete its row in the same change. The row is stale as soon as the
construction is gone, and the stale-entry check fails until the row is deleted.
"""

from __future__ import annotations

import ast

import pytest

from tests.unit._architecture_helpers import (
    assert_detector_catches_ast_snippets,
    assert_detector_ignores_ast_snippets,
    assert_violations_match_allowlist,
    iter_call_expressions,
    iter_test_module_trees,
    walk_with_enclosing_function,
)

#: Callees that build the app or a client for it, matched by name whether bare or an attribute.
APP_CONSTRUCTORS: frozenset[str] = frozenset({"create_app", "Flask", "FastAPI", "TestClient"})

#: The method that hands out a Flask test client, matched as an attribute only.
CLIENT_METHOD = "test_client"

#: The harness builds its apps under these prefixes, so the scan leaves them out.
_HARNESS_PREFIXES: tuple[str, ...] = ("tests/harness/", "tests/helpers/")

#: ``(repo-relative path, enclosing function or "<module>")`` of each place that built an app or a client
#: outside ``tests/harness/`` and ``tests/helpers/`` when this guard landed. SHRINK-ONLY: once a construction
#: is gone, the stale-entry check fails until its row is deleted. Each row is an open gap tracked by #2536.
KNOWN_APP_CONSTRUCTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("tests/admin/conftest.py", "admin_client"),  # FIXME(#2536)
        ("tests/admin/conftest.py", "ui_client"),  # FIXME(#2536)
        ("tests/admin/test_accounts_blueprint.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_accounts_blueprint.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_agent_probe_routes.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_agent_probe_routes.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_authorized_properties.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_authorized_properties.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_core_blueprint_create_tenant.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_core_blueprint_create_tenant.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_creatives_blueprint.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_creatives_blueprint.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_gam_placeholder_seeded_from_format_declarations.py", "operator"),  # FIXME(#2536)
        ("tests/admin/test_inventory_profiles.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_inventory_profiles.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_media_buy_approval_single_writer.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_media_buy_approval_single_writer.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_oidc_blueprint.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_oidc_blueprint.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_product_creation_integration.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_product_creation_integration.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_product_deletion_guard.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_product_deletion_guard.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_product_edit_error_contract.py", "operator"),  # FIXME(#2536)
        ("tests/admin/test_product_format_options_authoring.py", "operator"),  # FIXME(#2536)
        (
            "tests/admin/test_product_format_options_authoring.py",
            "test_the_create_form_carries_the_canonical_editor",
        ),  # FIXME(#2536)
        (
            "tests/admin/test_product_format_options_authoring.py",
            "test_the_edit_form_shows_the_declaration_the_product_carries",
        ),  # FIXME(#2536)
        ("tests/admin/test_publisher_partners_blueprint.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_publisher_partners_blueprint.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_settings_blueprint.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_settings_blueprint.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_users_blueprint.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_users_blueprint.py", "client"),  # FIXME(#2536)
        ("tests/admin/test_workflows_blueprint.py", "<module>"),  # FIXME(#2536)
        ("tests/admin/test_workflows_blueprint.py", "client"),  # FIXME(#2536)
        ("tests/conftest.py", "flask_app"),  # FIXME(#2536)
        ("tests/conftest.py", "flask_client"),  # FIXME(#2536)
        ("tests/integration/conftest.py", "<module>"),  # FIXME(#2536)
        ("tests/integration/conftest.py", "admin_client"),  # FIXME(#2536)
        ("tests/integration/conftest.py", "authenticated_admin_client"),  # FIXME(#2536)
        ("tests/integration/conftest.py", "test_admin_app"),  # FIXME(#2536)
        (
            "tests/integration/test_a2a_wire_integer_serialization.py",
            "test_real_a2a_get_adcp_capabilities_over_http_returns_integer_replay_ttl",
        ),  # FIXME(#2536)
        ("tests/integration/test_admin_ingest_url_policy.py", "management_api_client"),  # FIXME(#2536)
        (
            "tests/integration/test_app_lifespan_shutdown.py",
            "test_constructing_the_webhook_service_registers_no_shutdown_callback",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_app_lifespan_shutdown.py",
            "test_lifespan_awaits_every_registered_shutdown_callback",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_app_lifespan_shutdown.py",
            "test_lifespan_safe_when_no_callbacks_registered",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_app_lifespan_shutdown.py",
            "test_lifespan_swallows_a_failing_shutdown_callback",
        ),  # FIXME(#2536)
        ("tests/integration/test_audit_decorator.py", "test_decorator_extracts_custom_details"),  # FIXME(#2536)
        ("tests/integration/test_audit_decorator.py", "test_decorator_filters_password_fields"),  # FIXME(#2536)
        ("tests/integration/test_audit_decorator.py", "test_decorator_filters_sensitive_json_fields"),  # FIXME(#2536)
        ("tests/integration/test_audit_decorator.py", "test_decorator_handles_missing_session"),  # FIXME(#2536)
        ("tests/integration/test_audit_decorator.py", "test_decorator_logs_failed_actions"),  # FIXME(#2536)
        ("tests/integration/test_audit_decorator.py", "test_decorator_logs_successful_action"),  # FIXME(#2536)
        (
            "tests/integration/test_audit_decorator.py",
            "test_decorator_records_failure_when_the_handler_catches_and_returns",
        ),  # FIXME(#2536)
        ("tests/integration/test_audit_decorator.py", "test_decorator_skips_logging_without_tenant_id"),  # FIXME(#2536)
        ("tests/integration/test_audit_decorator.py", "test_decorator_truncates_long_values"),  # FIXME(#2536)
        (
            "tests/integration/test_debug_routes_agree_with_the_root_route.py",
            "test_the_debug_report_names_a_tenant_only_where_the_root_route_serves_one",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_debug_routes_agree_with_the_root_route.py",
            "test_the_debug_report_names_the_tenant_the_root_route_serves",
        ),  # FIXME(#2536)
        ("tests/integration/test_error_paths.py", "test_rest_error_with_valid_token_writes_audit_row"),  # FIXME(#2536)
        (
            "tests/integration/test_gam_oauth_tenant_binding.py",
            "test_callback_without_a_session_writes_nothing",
        ),  # FIXME(#2536)
        ("tests/integration/test_gam_tenant_setup.py", "test_admin_ui_network_detection_endpoint"),  # FIXME(#2536)
        ("tests/integration/test_health_route_migration.py", "test_health_routes_in_original_app"),  # FIXME(#2536)
        ("tests/integration/test_health_route_migration.py", "test_health_routes_in_refactored_app"),  # FIXME(#2536)
        (
            "tests/integration/test_landing_page_and_card_agree_on_origin.py",
            "test_the_page_and_the_card_publish_the_stored_origin",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_mock_adapter_publisher_sync.py",
            "test_sync_creates_authorized_property",
        ),  # FIXME(#2536)
        ("tests/integration/test_mock_adapter_publisher_sync.py", "test_sync_creates_property_tag"),  # FIXME(#2536)
        ("tests/integration/test_mock_adapter_publisher_sync.py", "test_sync_is_idempotent"),  # FIXME(#2536)
        (
            "tests/integration/test_mock_adapter_publisher_sync.py",
            "test_sync_property_has_verified_status",
        ),  # FIXME(#2536)
        ("tests/integration/test_notification_urls_exist.py", "app"),  # FIXME(#2536)
        ("tests/integration/test_product_deletion.py", "<module>"),  # FIXME(#2536)
        ("tests/integration/test_product_deletion.py", "client"),  # FIXME(#2536)
        ("tests/integration/test_self_service_signup.py", "client"),  # FIXME(#2536)
        (
            "tests/integration/test_self_service_signup.py",
            "test_oauth_callback_redirects_to_onboarding_for_signup_flow",
        ),  # FIXME(#2536)
        ("tests/integration/test_signing_conformance_vectors.py", "conformance_app"),  # FIXME(#2536)
        ("tests/integration/test_sync_api_gam_orders_import.py", "sync_api_client"),  # FIXME(#2536)
        ("tests/integration/test_template_url_validation.py", "<module>"),  # FIXME(#2536)
        ("tests/integration/test_tenant_management_api_integration.py", "app"),  # FIXME(#2536)
        ("tests/integration/test_tenant_management_api_integration.py", "client"),  # FIXME(#2536)
        ("tests/integration/test_tenant_management_api_integration.py", "sync_app"),  # FIXME(#2536)
        ("tests/integration/test_tenant_management_api_integration.py", "test_env_var_auth_succeeds"),  # FIXME(#2536)
        (
            "tests/integration/test_tenant_management_api_integration.py",
            "test_env_var_takes_priority_over_db",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_tenant_management_api_integration.py",
            "test_missing_header_returns_401",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_tenant_management_api_integration.py",
            "test_unconfigured_returns_503",
        ),  # FIXME(#2536)
        ("tests/integration/test_tenant_management_api_integration.py", "test_wrong_key_returns_401"),  # FIXME(#2536)
        (
            "tests/integration/test_tenant_origin_with_port.py",
            "test_one_stored_origin_serves_all_three_readers",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_virtual_host_is_mandatory.py",
            "test_a_ui_created_tenants_card_publishes_its_stored_origin",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_virtual_host_is_mandatory.py",
            "test_the_card_publishes_the_stored_origin_when_the_host_header_names_another",
        ),  # FIXME(#2536)
        (
            "tests/integration/test_virtual_host_is_mandatory.py",
            "test_the_host_wins_when_both_headers_name_a_served_tenant",
        ),  # FIXME(#2536)
        ("tests/unit/conftest.py", "_factory"),  # FIXME(#2536)
        ("tests/unit/test_a2a_transport_contract.py", "client"),  # FIXME(#2536)
        ("tests/unit/test_auth_helpers.py", "test_missing_header_returns_401"),  # FIXME(#2536)
        ("tests/unit/test_auth_helpers.py", "test_unconfigured_key_returns_503"),  # FIXME(#2536)
        ("tests/unit/test_auth_helpers.py", "test_valid_key_passes_through"),  # FIXME(#2536)
        ("tests/unit/test_auth_helpers.py", "test_wrong_key_returns_401"),  # FIXME(#2536)
        (
            "tests/unit/test_container_image_runs_as_built.py",
            "test_sync_job_posts_to_the_registered_trigger_route",
        ),  # FIXME(#2536)
        ("tests/unit/test_external_domain_routing.py", "test_a_host_no_tenant_claims_resolves_to_none"),  # FIXME(#2536)
        ("tests/unit/test_external_domain_routing.py", "test_index_route_external_domain_no_tenant"),  # FIXME(#2536)
        ("tests/unit/test_external_domain_routing.py", "test_index_route_external_domain_with_tenant"),  # FIXME(#2536)
        ("tests/unit/test_external_domain_routing.py", "test_index_route_subdomain_with_tenant"),  # FIXME(#2536)
        (
            "tests/unit/test_external_domain_routing.py",
            "test_the_admin_domain_is_not_a_tenant_and_is_never_looked_up",
        ),  # FIXME(#2536)
        ("tests/unit/test_external_domain_routing.py", "test_the_tenant_is_looked_up_by_the_host"),  # FIXME(#2536)
        (
            "tests/unit/test_fastapi_app_regression.py",
            "test_a2a_trailing_slash_redirects_to_canonical_path",
        ),  # FIXME(#2536)
        ("tests/unit/test_fastapi_app_regression.py", "test_admin_login_path_remains_available"),  # FIXME(#2536)
        ("tests/unit/test_fastapi_app_regression.py", "test_allowed_origin_gets_cors_header"),  # FIXME(#2536)
        (
            "tests/unit/test_fastapi_app_regression.py",
            "test_cors_does_not_use_wildcard_with_credentials",
        ),  # FIXME(#2536)
        ("tests/unit/test_fastapi_app_regression.py", "test_numeric_jsonrpc_id_converted_to_string"),  # FIXME(#2536)
        ("tests/unit/test_fastapi_app_regression.py", "test_receive_function_is_async"),  # FIXME(#2536)
        (
            "tests/unit/test_fastapi_app_regression.py",
            "test_root_login_path_is_exposed_by_root_fallback_mount",
        ),  # FIXME(#2536)
        ("tests/unit/test_signed_exchange_capture.py", "test_the_a2a_leg_really_reads_the_capture"),  # FIXME(#2536)
        ("tests/unit/test_signup_flow_session.py", "test_google_auth_clears_other_session_data"),  # FIXME(#2536)
        ("tests/unit/test_signup_flow_session.py", "test_google_auth_preserves_signup_flow_state"),  # FIXME(#2536)
        ("tests/unit/test_signup_flow_session.py", "test_google_auth_without_signup_flow"),  # FIXME(#2536)
        ("tests/unit/test_ssrf_url_validator.py", "_make_signals_agent_client"),  # FIXME(#2536)
        ("tests/unit/test_tenant_name_sync.py", "test_context_processor_handles_missing_tenant"),  # FIXME(#2536)
        ("tests/unit/test_tenant_name_sync.py", "test_context_processor_loads_fresh_tenant_data"),  # FIXME(#2536)
    }
)


def _is_app_construction(func: ast.expr) -> bool:
    """True when *func*, the callee of a call, builds the app or a client for it."""
    if isinstance(func, ast.Name):
        return func.id in APP_CONSTRUCTORS
    return isinstance(func, ast.Attribute) and (func.attr in APP_CONSTRUCTORS or func.attr == CLIENT_METHOD)


def find_app_constructions(tree: ast.Module) -> list[int]:
    """Line numbers of the calls in *tree* that build the app or a client for it.

    Ceiling: the match is by callee name, so the scan misses a constructor imported under another
    name (``from fastapi.testclient import TestClient as Client``).
    """
    return [call.lineno for call in iter_call_expressions(tree) if _is_app_construction(call.func)]


def scan() -> set[tuple[str, str]]:
    """``(path, enclosing function)`` for each app or client construction outside the harness.

    A call in a nested function keys under the innermost function. A call at module level, or in
    the body of a module-level class outside any method, keys under ``"<module>"``, which is what
    ``walk_with_enclosing_function`` gives. A call in the body of a class defined inside a function
    keys under that function.
    """
    return {
        (path, function)
        for path, tree in iter_test_module_trees()
        if not path.startswith(_HARNESS_PREFIXES)
        for node, function in walk_with_enclosing_function(tree)
        if isinstance(node, ast.Call) and _is_app_construction(node.func)
    }


def test_flags_each_construction_form():
    assert_detector_catches_ast_snippets(
        find_app_constructions,
        snippets={
            "create_app at module level": "app = create_app()\n",
            "qualified create_app": "app = admin.create_app(settings=s)\n",
            "Flask": "app = Flask(__name__)\n",
            "FastAPI": "app = FastAPI(lifespan=app_lifespan)\n",
            "TestClient": "client = TestClient(app)\n",
            "test_client method": "with app.test_client() as c:\n    pass\n",
        },
    )


def test_ignores_the_harness_names_and_unrelated_calls():
    assert_detector_ignores_ast_snippets(
        find_app_constructions,
        snippets={
            "harness helper": "app = admin_test_app()\n",
            "env client": "client = env.get_rest_client()\n",
            "a different test_client": "c = make_users_test_client()\n",
        },
    )


@pytest.mark.arch_guard
def test_tests_build_no_app_or_client_outside_the_harness():
    assert_violations_match_allowlist(
        scan(),
        set(KNOWN_APP_CONSTRUCTIONS),
        fix_hint="use the admin_client fixture, env.get_rest_client(), or tests/helpers/admin_session.admin_test_app()",
    )
