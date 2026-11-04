"""Flask's signed session cookie, read and written by the ASGI side (spec § 5.12.3).

The cookie stays Flask's: the same name, signed by the admin app's own session interface,
loaded with the app's own lifetime, flashes under ``_flashes`` as ``(category, message)``
pairs. A migrated route reads the mapping at ``request.state.session`` and writes to it;
when the mapping differs from what was loaded, the middleware appends one ``Set-Cookie``
carrying the attributes Flask's own session interface would give it. Both sides therefore
read what the other wrote, which is what lets a domain migrate while its neighbours stay.

The middleware is pure ASGI: it wraps ``send`` rather than buffering the response, so a
streamed or large page costs nothing extra.
"""

import copy
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import format_datetime
from http.cookies import SimpleCookie
from typing import Any

from flask import Flask
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _serializer(flask_app: Flask) -> URLSafeTimedSerializer:
    """The signer Flask's own cookie session interface uses; the admin app has a secret key."""
    interface = flask_app.session_interface
    assert isinstance(interface, SecureCookieSessionInterface), "the admin keeps its session in a signed cookie"
    serializer = interface.get_signing_serializer(flask_app)
    assert serializer is not None, "the admin app signs sessions, so it has a secret key"
    return serializer


class AdminSessionMiddleware:
    """Load Flask's session cookie into ``scope["state"]["session"]``; write it back if changed."""

    def __init__(self, app: ASGIApp, flask_app: Flask) -> None:
        self.app = app
        self.flask_app = flask_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        loaded = self._load(scope)
        state = scope.setdefault("state", {})
        state["session"] = copy.deepcopy(loaded)

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                current = state["session"]
                if current != loaded:
                    MutableHeaders(scope=message).append("set-cookie", self._cookie(current))
            await send(message)

        await self.app(scope, receive, send_with_cookie)

    def _load(self, scope: Scope) -> dict[str, Any]:
        """The session the request's cookie carries; ``{}`` when there is none or it is unreadable."""
        value = Request(scope).cookies.get(self.flask_app.config["SESSION_COOKIE_NAME"])
        if value is None:
            return {}
        try:
            return dict(_serializer(self.flask_app).loads(value, max_age=self._max_age()))
        except BadSignature:
            return {}

    def _max_age(self) -> int:
        return int(self.flask_app.permanent_session_lifetime.total_seconds())

    def _cookie(self, session: dict[str, Any]) -> str:
        """One ``Set-Cookie`` value with the attributes Flask's session interface gives its own."""
        app = self.flask_app
        interface = app.session_interface
        cookie: SimpleCookie = SimpleCookie()
        name = interface.get_cookie_name(app)
        if session:
            cookie[name] = _serializer(app).dumps(session)
            if session.get("_permanent"):
                expires = datetime.now(UTC) + app.permanent_session_lifetime
                cookie[name]["expires"] = format_datetime(expires, usegmt=True)
        else:
            cookie[name] = ""
            cookie[name]["max-age"] = 0
            cookie[name]["expires"] = format_datetime(datetime.fromtimestamp(0, UTC), usegmt=True)
        morsel = cookie[name]
        morsel["path"] = interface.get_cookie_path(app)
        domain = interface.get_cookie_domain(app)
        if domain:
            morsel["domain"] = domain
        if interface.get_cookie_secure(app):
            morsel["secure"] = True
        if interface.get_cookie_httponly(app):
            morsel["httponly"] = True
        samesite = interface.get_cookie_samesite(app)
        if samesite:
            morsel["samesite"] = samesite
        header = cookie.output(header="").strip()
        if interface.get_cookie_partitioned(app):
            header += "; Partitioned"
        return header


def flash(request: Request, message: str, category: str = "message") -> None:
    """Queue *message* for the next rendered page, the way ``flask.flash`` does."""
    request.state.session.setdefault("_flashes", []).append((category, message))


def get_flashed_messages(
    request: Request, with_categories: bool = False, category_filter: Iterable[str] = ()
) -> list[Any]:
    """Pop the queued flashes on first call; later calls in the same request see the same list.

    Shapes and filters exactly as ``flask.get_flashed_messages``.
    """
    flashes = getattr(request.state, "flashes", None)
    if flashes is None:
        session = request.state.session
        flashes = list(session.pop("_flashes")) if "_flashes" in session else []
        request.state.flashes = flashes
    wanted = tuple(category_filter)
    if wanted:
        flashes = [pair for pair in flashes if pair[0] in wanted]
    if not with_categories:
        return [pair[1] for pair in flashes]
    return list(flashes)
