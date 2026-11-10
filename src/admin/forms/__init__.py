"""The accepted input shape of every admin write route (spec § 5.5).

A route parses the posted form into one of these models with :func:`parse_form` and hands
the model to a service; a field the model does not declare is dropped, a blank string is
absent, a missing required field or a value of the wrong type is an ``AdminInvalidInput``
naming the field. The models import nothing from any web framework.
"""

from src.admin.forms._base import FormModel, parse_form

__all__ = ["FormModel", "parse_form"]
