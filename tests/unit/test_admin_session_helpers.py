"""The ASGI-side admin session helpers (spec § 5.9.3): one payload, two carriers.

A bare Flask app with a known secret stands in for the admin app; an ``httpx.Response``
carrying a ``Set-Cookie`` stands in for an answer from the ASGI test client.
"""

import httpx
import pytest
from flask import Flask

from tests.helpers.admin_session import (
    _session_payload,
    admin_auth_cookie,
    admin_session_cookie,
    cookie_flashes,
    session_cookie_payload,
    signed_session_cookie,
)


@pytest.fixture
def app() -> Flask:
    app = Flask("unit")
    app.secret_key = "unit"
    return app


def _response_with_cookie(cookie: str) -> httpx.Response:
    return httpx.Response(
        302,
        headers={"set-cookie": f"session={cookie}; Path=/"},
        request=httpx.Request("POST", "http://testserver/x"),
    )


def test_admin_auth_cookie_round_trips_through_flasks_own_serializer(app):
    cookie = admin_auth_cookie(app, "t1")
    assert app.session_interface.get_signing_serializer(app).loads(cookie) == _session_payload("t1")


def test_admin_session_cookie_signs_the_same_payload_with_the_given_secret():
    app = Flask("unit")
    app.secret_key = "unit"
    cookie = admin_session_cookie("t1", secret_key="unit")
    assert app.session_interface.get_signing_serializer(app).loads(cookie) == _session_payload("t1")


def test_session_cookie_payload_reads_the_cookie_the_response_set(app):
    response = _response_with_cookie(signed_session_cookie(app, {"_flashes": [("error", "bad")]}))
    assert session_cookie_payload(app, response) == {"_flashes": [("error", "bad")]}
    assert cookie_flashes(app, response) == [("error", "bad")]


def test_session_cookie_payload_is_empty_without_a_cookie(app):
    response = httpx.Response(200, request=httpx.Request("GET", "http://testserver/x"))
    assert session_cookie_payload(app, response) == {}


def test_a_cookie_signed_with_another_secret_reads_as_empty(app):
    other = Flask("other")
    other.secret_key = "other"
    assert session_cookie_payload(app, _response_with_cookie(signed_session_cookie(other, {"user": "x"}))) == {}
