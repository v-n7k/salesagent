"""The agent form models and ``parse_form`` (spec § 5.5): the accepted shape of a write route."""

import pytest

from src.admin.errors import AdminInvalidInput
from src.admin.forms import parse_form
from src.admin.forms.agents import CreativeAgentForm, SignalsAgentForm

URL = "https://1.1.1.1/mcp"


def test_blank_url_is_required():
    with pytest.raises(AdminInvalidInput) as refused:
        parse_form(CreativeAgentForm, {"agent_url": "   ", "name": "n"})
    assert refused.value.message == "Agent URL is required"


def test_missing_name_is_required():
    with pytest.raises(AdminInvalidInput) as refused:
        parse_form(SignalsAgentForm, {"agent_url": URL})
    assert refused.value.message == "Agent name is required"


def test_first_error_wins_in_declaration_order():
    with pytest.raises(AdminInvalidInput) as refused:
        parse_form(CreativeAgentForm, {})
    assert refused.value.message == "Agent URL is required"


def test_checkbox_defaults_trimming_and_unknown_fields():
    form = parse_form(
        CreativeAgentForm, {"agent_url": f" {URL} ", "name": "  Spaced  ", "enabled": "on", "csrf_token": "x"}
    )
    assert (form.agent_url, form.name, form.enabled, form.priority, form.auth_type, form.auth_credentials) == (
        URL,
        "Spaced",
        True,
        10,
        None,
        None,
    )


def test_signals_defaults_when_only_the_required_fields_are_posted():
    form = parse_form(SignalsAgentForm, {"agent_url": URL, "name": "n"})
    assert (form.enabled, form.forward_promoted_offering, form.timeout, form.auth_header) == (False, False, 30, None)


def test_non_integer_number_names_the_field():
    with pytest.raises(AdminInvalidInput) as refused:
        parse_form(SignalsAgentForm, {"agent_url": URL, "name": "n", "timeout": "abc"})
    assert refused.value.message == "Timeout: Input should be a valid integer, unable to parse string as an integer"
