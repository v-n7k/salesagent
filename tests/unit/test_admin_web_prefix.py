"""The link prefix a migrated route sees (spec § 5.12.4): precedence and the plain-path rule.

A ``starlette.requests.Request`` is built from a bare scope: no app, no client.
"""

import pytest
from starlette.requests import Request

from src.admin.web.templates import admin_prefix, request_url


def _request(headers: dict[str, str], root_path: str, path: str = "/tenant/t1/probe/links") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "root_path": root_path,
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.mark.parametrize(
    ("headers", "root_path", "expected"),
    [
        ({}, "", ""),
        ({}, "/admin", "/admin"),
        ({"x-forwarded-prefix": "/admin"}, "", "/admin"),
        ({"x-forwarded-prefix": "/admin"}, "/admin", "/admin"),
        ({"x-forwarded-prefix": "/admin/"}, "", "/admin"),
        ({"x-script-name": "/x", "x-forwarded-prefix": "/admin"}, "", "/x"),
        ({"x-forwarded-prefix": "https://attacker.example"}, "", ""),
        ({"x-forwarded-prefix": "//attacker.example"}, "/admin", "/admin"),
    ],
)
def test_admin_prefix_precedence_and_plain_path_rule(headers, root_path, expected):
    assert admin_prefix(_request(headers, root_path)) == expected


def test_request_url_carries_the_prefix_the_operator_sees():
    assert (
        request_url(_request({"x-forwarded-prefix": "/admin"}, "")) == "http://testserver/admin/tenant/t1/probe/links"
    )
    assert (
        request_url(_request({}, "/admin", path="/admin/tenant/t1/probe/links"))
        == "http://testserver/admin/tenant/t1/probe/links"
    )
