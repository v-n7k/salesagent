"""``FormModel`` and ``parse_form``: posted strings in, a typed model or one refusal out."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from src.admin.errors import AdminInvalidInput


class FormModel(BaseModel):
    """A posted form: unknown fields are ignored, strings are stripped, lax parsing for the rest.

    pydantic's lax mode turns ``"on"`` into ``True`` and ``"10"`` into ``10``, so a checkbox and
    a number field need no validator of their own.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


def parse_form[FormT: FormModel](model: type[FormT], data: Mapping[str, Any]) -> FormT:
    """Validate *data* into *model*; a blank string counts as absent.

    The refusal carries the FIRST error only, in declaration order: ``"<Title> is required"``
    for a missing field, ``"<Title>: <pydantic's message>"`` for anything else.
    """
    posted = {key: value for key, value in data.items() if not (isinstance(value, str) and not value.strip())}
    try:
        return model.model_validate(posted)
    except ValidationError as exc:
        first = exc.errors()[0]
        name = str(first["loc"][0])
        title = model.model_fields[name].title or name
        if first["type"] == "missing":
            raise AdminInvalidInput(f"{title} is required") from exc
        raise AdminInvalidInput(f"{title}: {first['msg']}") from exc
