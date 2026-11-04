"""The admin sub-application (spec § 5.12.1): FastAPI routers first, the Flask admin last.

``build_admin_app`` returns one ASGI application that ``src/app.py`` mounts where the bare
WSGI adapter was: the migrated routers answer the routes they own, and every other path falls
through to the Flask admin mounted last. The two apps share the session cookie (the
middleware), the templates (``render``) and the endpoint names (``url_for`` on both sides),
so a domain moves without its templates or its neighbours noticing.
"""

from collections.abc import Sequence
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


#: The ``flask_app.extensions`` key under which ``build_admin_app`` registers the sub-application
#: it built over a Flask app, so that app's ``url_for`` resolves against the routers it was given.
ADMIN_ASGI_APP = "admin_asgi_app"


def _migrated_routers(flask_app: Flask) -> Sequence[Any]:
    """Where a Flask-side ``url_for`` looks for a name it cannot build: the sub-application built
    over *flask_app* when there is one (a test's probe router rides along), else the registered
    routers, so a bare Flask app resolves every migrated endpoint too."""
    built = flask_app.extensions.get(ADMIN_ASGI_APP)
    return [built] if built is not None else list(ADMIN_ROUTERS)


def install_migrated_endpoint_resolver(flask_app: Flask) -> None:
    """Install the Flask-side half of ``url_for`` on *flask_app*; ``create_app`` calls this once.

    Flask calls the handler with the values it could not build from, including the ``_anchor``,
    ``_method``, ``_scheme`` and ``_external`` it adds back; those are stripped before the
    routers are asked. An endpoint no router knows re-raises Flask's own ``BuildError``, which
    Flask then raises as it would have without this handler.
    """

    def resolve(error: Exception, endpoint: str, values: dict[str, Any]) -> str:
        path_values = dict(values)
        external = path_values.pop("_external", None)
        for key in ("_anchor", "_method", "_scheme"):
            path_values.pop(key, None)
        for router in _migrated_routers(flask_app):
            try:
                path = str(router.url_path_for(endpoint, **path_values))
                break
            except NoMatchFound:
                continue
        else:
            raise error from None
        url = flask.request.script_root + path
        if external:
            url = flask.request.host_url.rstrip("/") + url
        return url

    flask_app.url_build_error_handlers.append(resolve)


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
    flask_app.extensions[ADMIN_ASGI_APP] = app
    return app
