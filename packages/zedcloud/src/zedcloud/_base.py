"""Base types shared by all generated models.

Zedcloud evolves faster than any SDK release, so models are deliberately
tolerant of responses the spec does not describe:

* unknown fields are kept (``extra="allow"``) and round-trip on dump, so a
  GET → modify → PUT cycle never silently drops server-side configuration;
* enums accept values added server-side after this SDK was generated;
* timestamps the server formats unexpectedly are kept as the raw string
  instead of failing the whole response.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, ValidationError, WrapValidator
from pydantic_core.core_schema import ValidatorFunctionWrapHandler


class OpenEnum(str, Enum):
    """String enum that also accepts values unknown at generation time.

    Unknown values become pseudo-members: ``isinstance(v, TheEnum)`` holds,
    ``v == "NEW_VALUE"`` compares as a string, and ``v.is_known`` is False.
    """

    @classmethod
    def _missing_(cls, value: object) -> OpenEnum | None:
        if not isinstance(value, str):
            return None
        member = str.__new__(cls, value)
        member._name_ = value
        member._value_ = value
        return member

    @property
    def is_known(self) -> bool:
        """Whether this value was part of the API spec the SDK was built from."""
        return self._name_ in type(self).__members__

    def __str__(self) -> str:
        return str(self.value)


def _lenient_datetime(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    try:
        return handler(value)
    except ValidationError:
        if isinstance(value, str):
            return value
        raise


Timestamp = Annotated[datetime, WrapValidator(_lenient_datetime)]
"""A ``datetime``; falls back to the raw string if the server's format is unparseable."""


class ZedcloudModel(BaseModel):
    """Base class for every generated Zedcloud model.

    Fields use snake_case in Python and the API's camelCase on the wire; both
    spellings are accepted when constructing a model.
    """

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        defer_build=True,
        protected_namespaces=(),
        use_attribute_docstrings=False,
    )

    def to_api(self) -> dict[str, Any]:
        """Serialize for a request body: API field names, ``None`` fields omitted."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)
