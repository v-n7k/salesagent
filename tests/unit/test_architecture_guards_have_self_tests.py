"""Guard: every guard module calls a shared self-test helper.

A guard that has never been seen to fail is not known to grade anything
(tests/unit/CLAUDE.md, "A guard must be seen to fail"). The shared helpers in
``tests/unit/_architecture_helpers.py`` each show one kind of guard failing on a
known defect, and this guard requires every guard module to call at least one of
them (``SELF_TEST_HELPERS``):

- ``assert_detector_catches_ast_snippets``: an AST detector flags known-bad source.
- ``assert_detector_ignores_ast_snippets``: the detector passes known-good source.
- ``anchor_consistency_detects_drift``: an anchor check reports sources that disagree.
- ``write_ast_grep_probe`` and ``stage_ast_grep_root``: an ast-grep rule matches a
  probe file written into a disposable copy of the real rules.
- ``assert_check_rejects_mutation``: a check that reads files passes on a copy of them
  and rejects the copy once it has been broken.

A guard module is a ``tests/unit/`` module named with one of ``GUARD_MODULE_PREFIXES``.
It passes when a call in it names one of ``SELF_TEST_HELPERS``, either bare or as an
attribute (``helpers.write_ast_grep_probe(...)``). An import with no call does not pass.

``KNOWN_WITHOUT_SELF_TEST`` lists the modules that called none when this guard landed
(#2534). It only shrinks, and every row carries ``# FIXME(#2534)``. Give a new guard
module a self-test instead of adding a row for it.

To leave the list, call a helper from the module and delete its row in the same change.
The row is stale as soon as the call exists, and the stale-entry check fails until the
row is deleted.
"""

from __future__ import annotations

import ast

import pytest

from tests.unit._architecture_helpers import (
    assert_detector_catches_ast_snippets,
    assert_detector_ignores_ast_snippets,
    assert_violations_match_allowlist,
    called_function_names,
    iter_architecture_guard_trees,
)

SELF_TEST_HELPERS: frozenset[str] = frozenset(
    {
        "assert_detector_catches_ast_snippets",
        "assert_detector_ignores_ast_snippets",
        "anchor_consistency_detects_drift",
        "write_ast_grep_probe",
        "stage_ast_grep_root",
        "assert_check_rejects_mutation",
    }
)

#: Repo-relative paths of the guard modules that called no helper when this guard landed.
#: SHRINK-ONLY: once a module gains a helper call, the stale-entry check fails until its
#: row is deleted. Each row is an open gap tracked by #2534.
KNOWN_WITHOUT_SELF_TEST: frozenset[tuple[str]] = frozenset(
    {
        ("tests/unit/test_architecture_account_brand_guard.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_account_row_construction.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_admin_templates_exist.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_app_lifespan_lazy_import.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_audit_scripts_have_a_subject.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_auth_helper_signature.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_assertion_strength.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_breaker_scenarios_graded_live.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_ctx_keys.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_decisions_verdict_contract.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_dispatch_entries.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_envelope_scenario_preserved.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_ext_fallback_xfail.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_feature_parse.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_generator_collected_features.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_1462_xfail_reason.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_dict_registry.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_direct_call_impl.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_duplicate_steps.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_partial_account_call_impl.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_pass_steps.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_request_in_then.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_response_subscript.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_shadowed_steps.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_silent_env.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_stale_xfail_citations.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_no_trivial_assertions.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_package_sentences.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_scenario_liveness.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_single_db_scope_entry.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_stale_xfail_reason_text.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_step_module_reachability.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_step_text_alignment.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_unrouted_is_refused.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_wire_discipline.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_bdd_xfail_reason_tokens.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_behavioral_mock_cap.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_capability_constant_parity.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_census_verdict_contract.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_ci_suite_coverage.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_counterparty_egress_gated.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_create_paths_share_creative_validation.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_creative_lookup_principal_scoped.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_creative_status_vocabulary.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_discovery_code_collapse.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_dockerfile_digest_pinned.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_dto_adds_no_field.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_e2e_compose_tls_origins.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_e2e_counterparty_origin_wiring.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_e2e_origin_services_start.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_e2e_scripted_llm_wiring.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_e2e_webhook_capture_wiring.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_e2e_webhook_receivers_migrated.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_enum_value_normalization.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_env_route_agreement.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_error_recovery_enum_conformance.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_feature_file_bound.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_fixture_tenant_matches_production.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_format_fetch_single_path.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_function_local_imports_resolve.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_harness_identity_sentinel.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_harness_single_dispatch.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_healthcheck_start_period.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_image_supply_chain.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_impl_result_envelope.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_import_usage.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_local_schema_imports.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_media_buy_carrier_projection.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_migration_completeness.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_natural_key_immutability.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_nested_unit_of_work.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_async_callable_submitted_sync.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_bare_basemodel.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_bare_shadowed_imports.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_base_notfound_raise.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_broad_except_validation_relabel.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_defensive_rootmodel.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_duplicate_admin_auth_block.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_duplicate_module_defs.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_error_construction_in_impl.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_error_flattening.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_handrolled_allowlist_diff.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_handrolled_call_walk.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_handrolled_race_recovery.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_hardcoded_unsigned_webhook.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_outbound_insecure_hatch.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_packages_field_literal.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_private_destinations.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_raw_adagents_error_text.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_raw_media_package_select.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_raw_select.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_raw_thread_registry.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_response_side_persisted_defaults.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_silent_except.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_test_only_exports.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_value_error_in_impl.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_no_webhook_egress_text_payload.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_one_status_coercion.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_one_webhook_url_validator.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_one_wire_body.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_one_wire_error_assertion.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_one_wire_serializer_seat.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_pre_commit_coverage_map.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_pre_commit_hook_count.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_pre_commit_no_additional_deps.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_query_type_safety.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_ratchet_counters_measure_the_invariant.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_ratchet_counters_prove_completion.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_ratchet_enforcement.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_ratchet_hooks_use_driver.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_registration_holds_sdk_config.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_repo_invariants.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_repository_pattern.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_required_ci_checks_frozen.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_reserved_tld_single_matcher.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_route_xfail_census.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_scenario_liveness_join.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_sdk_idempotency_seam.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_signing_block_construction.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_signing_operations.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_single_migration_head.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_sync_accounts_field_policy.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_tenant_context_parity.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_test_marker_coverage.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_uow_effect_boundary.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_weak_mock_assertions.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_webhook_auth_derivation.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_webhook_ingest_validation.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_webhook_sender_boundary.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_well_known_material_isolation.py",),  # FIXME(#2534)
        ("tests/unit/test_architecture_workflow_tenant_isolation.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_a2a_integer_restoration.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_adapter_capability_raise.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_authorized_list_mutation.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_bdd_dormancy_classifier.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_bdd_duplicate_step_literals.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_bdd_no_duplicate_elif_branches.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_bdd_strict_xfail_representative.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_creative_input_raise.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_error_code_fixture_pin.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_json_dumps_jsontype.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_jsontype_append_rmw.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_narrowed_integrity_recovery.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_no_adhoc_testclient_bypass.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_no_beads_ids.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_no_duplicate_conformant_receiver_verifier.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_no_duplicate_e2e_tls_ca_reads.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_no_fabricated_example_domain.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_no_raw_exception_in_admin_response.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_no_webhook_sender_on_the_raw_seam.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_normalize_agent_url_delegates.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_orm_constructor_kwargs.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_outbound_adcp_client_seam.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_resolvable_predicates_attempt_resolution.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_toolresult_structured_content_model_dump.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_uniqueness_index_verdict.py",),  # FIXME(#2534)
        ("tests/unit/test_guards_validation_boundary_suggestion.py",),  # FIXME(#2534)
    }
)


def find_guards_without_self_test(tree: ast.Module) -> list[int]:
    """``[1]`` when no call in *tree* names a self-test helper, else ``[]``.

    A module has no single line to blame, so a failing module reports line 1.

    Ceiling: a call anywhere in the module counts, including one in a function that no
    test calls. If that proves too lenient, require the call to sit inside a ``test_*``
    function.
    """
    return [] if called_function_names(tree) & SELF_TEST_HELPERS else [1]


@pytest.mark.arch_guard
def test_every_guard_module_calls_a_shared_self_test_helper():
    found = {(str(rel),) for tree, rel in iter_architecture_guard_trees() if find_guards_without_self_test(tree)}
    assert_violations_match_allowlist(
        found,
        set(KNOWN_WITHOUT_SELF_TEST),
        fix_hint="call one of SELF_TEST_HELPERS in the guard module; remove the row when it does",
    )


def test_meta_guard_flags_a_module_with_no_helper_call():
    assert_detector_catches_ast_snippets(
        find_guards_without_self_test,
        snippets={
            "assert only": "def test_x():\n    assert scan() == set()\n",
            "hand-rolled self-test": "def test_self():\n    assert find(ast.parse('bad()'))\n",
        },
    )


def test_meta_guard_accepts_each_helper_by_name_and_as_attribute():
    assert_detector_ignores_ast_snippets(
        find_guards_without_self_test,
        snippets={name: f"def test_x():\n    {name}(f, snippets={{}})\n" for name in SELF_TEST_HELPERS}
        | {"attribute form": "def test_x():\n    helpers.anchor_consistency_detects_drift(s, m, label='x')\n"},
    )
