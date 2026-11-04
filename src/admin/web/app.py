"""The admin sub-application (spec § 5.12.1): FastAPI routers first, the Flask admin last.

``build_admin_app`` returns one ASGI application that ``src/app.py`` mounts where the bare
WSGI adapter was: the migrated routers answer the routes they own, and every other path falls
through to the Flask admin mounted last. The two apps share the session cookie (the
middleware), the templates (``render``) and the endpoint names (``url_for`` on both sides),
so a domain moves without its templates or its neighbours noticing.
"""

from collections.abc import Callable, Sequence
from typing import Any

import flask
from a2wsgi import WSGIMiddleware
from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from flask import Flask
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import NoMatchFound

from src.admin.routers import ADMIN_ROUTERS
from src.admin.web.guards import AccessDenied, AuthRequired, answer_access_denied, answer_auth_required
from src.admin.web.session import AdminSessionMiddleware


def answer_not_found(request: Request, exc: Exception) -> PlainTextResponse:
    """A path parameter that does not fit its type is a URL that names nothing: 404, not 422."""
    return PlainTextResponse("Not Found", status_code=404)


def _migrated_endpoint_resolver(admin_app: FastAPI) -> Callable[[Exception, str, dict[str, Any]], str]:
    """The Flask-side half of ``url_for``: resolve an endpoint that has moved to a router.

    Flask calls this with the values it could not build from, including the ``_anchor``,
    ``_method``, ``_scheme`` and ``_external`` it adds back; those are stripped before the
    sub-application is asked. An endpoint the sub-application does not know re-raises Flask's
    own ``BuildError``, which Flask then raises as it would have without this handler.
    """

    def resolve(error: Exception, endpoint: str, values: dict[str, Any]) -> str:
        path_values = dict(values)
        external = path_values.pop("_external", None)
        for key in ("_anchor", "_method", "_scheme"):
            path_values.pop(key, None)
        try:
            path = str(admin_app.url_path_for(endpoint, **path_values))
        except NoMatchFound:
            raise error from None
        url = flask.request.script_root + path
        if external:
            url = flask.request.host_url.rstrip("/") + url
        return url

    return resolve


def build_admin_app(flask_app: Flask, *, routers: Sequence[APIRouter] | None = None) -> FastAPI:
    """The sub-application over *flask_app*: *routers* (default ``ADMIN_ROUTERS``), then Flask."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.state.flask_app = flask_app
    app.add_middleware(AdminSessionMiddleware, flask_app=flask_app)
    for router in ADMIN_ROUTERS if routers is None else routers:
        app.include_router(router)
    app.add_exception_handler(RequestValidationError, answer_not_found)
    app.add_exception_handler(AuthRequired, answer_auth_required)
    app.add_exception_handler(AccessDenied, answer_access_denied)
    # a2wsgi's adapter is an ASGI app at runtime; mypy sees a protocol mismatch on both
    # sides of the call (the same ignore the previous mount in src/app.py carried).
    app.mount("", WSGIMiddleware(flask_app))  # type: ignore[arg-type, unused-ignore]
    flask_app.url_build_error_handlers.append(_migrated_endpoint_resolver(app))
    return app
