"""Migrated admin routes: one module per domain, registered here (spec § 5.1).

A router module declares its ``APIRouter``s with the domain's URL prefix, names every route
``<blueprint>.<function>`` so the endpoint names the templates link to do not change, puts the
guard on the route decorator as a dependency and the audit wrapper directly under it, reads a
form through ``form_data``, calls a service function, and answers through
``src.admin.web.responses``. It imports nothing from Flask, SQLAlchemy, the ORM models or the
session factory, and catches nothing but ``AdminRefusal``.
"""

from fastapi import APIRouter

#: Every migrated router, in registration order. ``build_admin_app`` includes these when it is
#: given no explicit list; a test passes its own probe router instead.
ADMIN_ROUTERS: tuple[APIRouter, ...] = ()
