"""Links and pages for a migrated route (spec § 5.12.4, § 5.12.5).

The link prefix is what ``CustomProxyFix`` gives the Flask side: ``X-Script-Name``, else
``X-Forwarded-Prefix``, else the path the sub-application is mounted at. ``url_for`` resolves a
migrated endpoint on the sub-application first and falls back to the Flask URL map, so a
template links to either side with one call and the same names. ``render`` goes through the
Flask app's own Jinja environment, so the templates do not change while their routes move.
"""

from functools import partial
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import NoMatchFound

from src.admin.web.session import get_flashed_messages
from src.core.domain_config import get_support_email


def _is_plain_path(value: str) -> bool:
    """A prefix a proxy may set: one leading slash, never a scheme or a host."""
    return value.startswith("/") and not value.startswith("//") and "://" not in value


def admin_prefix(request: Request) -> str:
    """The prefix every link carries: a proxy header when it is a plain path, else the mount path."""
    for header in ("x-script-name", "x-forwarded-prefix"):
        value = request.headers.get(header, "")
        if value and _is_plain_path(value):
            return value.rstrip("/")
    return str(request.scope.get("root_path", "")).rstrip("/")


def _route_path(request: Request) -> str:
    """The request path below the mount: ``scope["path"]`` without its ``root_path``."""
    path = str(request.scope["path"])
    root_path = str(request.scope.get("root_path", ""))
    if root_path and path.startswith(root_path):
        return path[len(root_path) :]
    return path


def request_url(request: Request) -> str:
    """The request's own absolute URL with the prefix the operator sees (for ``next=``)."""
    return str(request.url.replace(path=admin_prefix(request) + _route_path(request)))


def url_for(request: Request, endpoint: str, **values: Any) -> str:
    """The URL of *endpoint*, migrated or not, under the request's prefix.

    A migrated route resolves on the sub-application; anything else resolves on the Flask URL
    map bound to this request's host and prefix (Werkzeug puts unknown values in the query
    string, which is how ``next=`` travels). An unknown endpoint raises Werkzeug's
    ``BuildError``: that is a bug in a template, not a condition to answer.
    """
    prefix = admin_prefix(request)
    try:
        return prefix + str(request.app.url_path_for(endpoint, **values))
    except NoMatchFound:
        pass
    adapter = request.app.state.flask_app.url_map.bind(
        server_name=request.headers.get("host", "localhost"),
        script_name=prefix,
        url_scheme=request.url.scheme,
    )
    return str(adapter.build(endpoint, dict(values)))


def render(request: Request, template_name: str, **values: Any) -> HTMLResponse:
    """Render *template_name* through the Flask app's Jinja environment.

    Supplies what the Flask side supplies: ``url_for``, ``get_flashed_messages``, ``session``,
    ``script_name`` and ``support_email``. A caller's value wins over these. Nothing else is
    injected (no ``request``, ``g`` or ``config``): a template that needs a value is given it
    by its route.
    """
    template = request.app.state.flask_app.jinja_env.get_template(template_name)
    page: dict[str, Any] = {
        "url_for": partial(url_for, request),
        "get_flashed_messages": partial(get_flashed_messages, request),
        "session": request.state.session,
        "script_name": admin_prefix(request),
        "support_email": get_support_email(),
    }
    page.update(values)
    return HTMLResponse(template.render(page))
