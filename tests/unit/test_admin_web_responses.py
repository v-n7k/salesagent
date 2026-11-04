"""The admin refusal family and the plain response helpers (spec § 5.6, § 5.7).

Pure functions: no app, no request. ``json.loads(response.body)`` reads a body.
"""

import json

from src.admin.errors import AdminConflict, AdminInvalidInput, AdminNotFound
from src.admin.web.responses import json_error, json_ok, redirect


def test_refusal_statuses_and_message():
    assert (AdminNotFound("x").status, AdminInvalidInput("x").status, AdminConflict("x").status) == (404, 400, 409)
    assert (str(AdminNotFound("gone")), AdminNotFound("gone").message) == ("gone", "gone")


def test_json_ok_carries_success_and_fields():
    response = json_ok(count=3, samples=["a"])
    assert (response.status_code, json.loads(response.body)) == (200, {"success": True, "count": 3, "samples": ["a"]})


def test_json_error_carries_message_and_status():
    response = json_error("nope", 404)
    assert (response.status_code, json.loads(response.body)) == (404, {"success": False, "error": "nope"})


def test_redirect_is_a_302():
    response = redirect("/back")
    assert (response.status_code, response.headers["location"]) == (302, "/back")
