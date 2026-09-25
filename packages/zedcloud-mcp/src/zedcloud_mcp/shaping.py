"""Shape API responses for a language model's context window.

Responses are converted to plain JSON, empty values dropped, long lists and
strings truncated (with an explicit marker), and secret-looking fields
redacted. Enum prefixes such as ``RUN_STATE_`` are kept, since they are the
values filters and bodies expect.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from zedcloud_mcp.guard import redact

MAX_STRING = 4000


def to_json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, list):
        return [to_json(v) for v in value]
    return value


def prune(value: Any, *, max_items: int, max_string: int = MAX_STRING) -> Any:
    """Drop empty values; truncate long lists and strings."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            pruned = prune(item, max_items=max_items, max_string=max_string)
            if pruned not in (None, "", [], {}):
                out[key] = pruned
        return out
    if isinstance(value, list):
        items = [prune(v, max_items=max_items, max_string=max_string) for v in value[:max_items]]
        if len(value) > max_items:
            items.append(f"… {len(value) - max_items} more items omitted (raise max_items)")
        return items
    if isinstance(value, str) and len(value) > max_string:
        return value[:max_string] + f"… [{len(value) - max_string} more characters]"
    return value


def select_fields(value: Any, fields: list[str] | None) -> Any:
    """Keep only ``fields`` (API names) on an object, or on each item of its ``list``."""
    if not fields:
        return value
    wanted = set(fields)

    def pick(obj: Any) -> Any:
        return {k: v for k, v in obj.items() if k in wanted} if isinstance(obj, dict) else obj

    if isinstance(value, dict) and isinstance(value.get("list"), list):
        return {**value, "list": [pick(v) for v in value["list"]]}
    if isinstance(value, list):
        return [pick(v) for v in value]
    return pick(value)


def shape(value: Any, *, max_items: int = 50, fields: list[str] | None = None) -> Any:
    return prune(redact(select_fields(to_json(value), fields)), max_items=max_items)


def row(obj: Any, keys: dict[str, str]) -> dict[str, Any]:
    """Project a model onto ``{output_key: attribute}``, skipping empty values."""
    out: dict[str, Any] = {}
    for label, attr in keys.items():
        value = getattr(obj, attr, None)
        value = getattr(value, "value", value)
        if value not in (None, "", [], {}):
            out[label] = value
    return out
