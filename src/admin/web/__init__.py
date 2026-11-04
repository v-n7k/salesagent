"""The ASGI admin foundation (spec § 5.12).

The admin is migrating from Flask blueprints to FastAPI routers one domain at a time. This
package is the sub-application the migrated routers live on, and the five services every
migrated route reads through:

* ``app`` — ``build_admin_app(flask_app)``: the FastAPI sub-application, with the Flask admin
  mounted last as the fallback for every route not yet migrated.
* ``session`` — the pure-ASGI middleware that reads and writes Flask's signed session
  cookie, plus ``flash`` / ``get_flashed_messages`` over it.
* ``templates`` — the link prefix, ``url_for`` in both directions, and ``render`` through
  Flask's Jinja environment.
* ``guards`` — ``require_tenant_access`` as a FastAPI dependency over the same decision
  the Flask decorator makes.
* ``audit`` — ``audited`` over the same audit record the Flask decorator writes, and the
  one form-reading dependency.
* ``responses`` — the JSON envelope, the 302, and the two refusal answers.
"""
