"""Registry of every Zedcloud API operation, generated from the OpenAPI specs.

Useful for tooling that needs to discover operations at runtime (the MCP
server, CLIs, test harnesses)::

    from zedcloud.operations import get_operation, search_operations

    op = get_operation("EdgeNodeConfiguration_QueryEdgeNodes")
    op.risk            # "read" | "write" | "destructive"
    search_operations("reboot device")
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

Risk = Literal["read", "write", "destructive"]


@dataclass(frozen=True)
class OperationParam:
    name: str
    python_name: str
    location: str  # path | query | header | body
    type: str
    required: bool
    description: str
    enum: tuple[str, ...] | None = None
    multi_segment: bool = False


@dataclass(frozen=True)
class Operation:
    operation_id: str
    service: str
    method_name: str
    http_method: str
    path: str
    summary: str
    description: str
    tags: tuple[str, ...]
    risk: Risk
    deprecated: bool
    paginated: bool
    body_model: str | None
    response_model: str | None
    item_model: str | None
    params: tuple[OperationParam, ...]

    @property
    def path_params(self) -> tuple[OperationParam, ...]:
        return tuple(p for p in self.params if p.location == "path")

    @property
    def query_params(self) -> tuple[OperationParam, ...]:
        return tuple(p for p in self.params if p.location == "query")

    @property
    def header_params(self) -> tuple[OperationParam, ...]:
        return tuple(p for p in self.params if p.location == "header")

    @property
    def has_body(self) -> bool:
        return any(p.location == "body" for p in self.params)

    @property
    def is_read_only(self) -> bool:
        return self.risk == "read"

    def summary_line(self) -> str:
        return f"{self.operation_id}: {self.http_method} {self.path} — {self.summary} [{self.risk}]"


@lru_cache(maxsize=1)
def _load() -> dict[str, Operation]:
    raw = json.loads(resources.files("zedcloud._generated").joinpath("operations.json").read_text())
    ops: dict[str, Operation] = {}
    for entry in raw["operations"]:
        params = tuple(
            OperationParam(
                name=p["name"],
                python_name=p["python_name"],
                location=p["in"],
                type=p["type"],
                required=p["required"],
                description=p["description"],
                enum=tuple(p["enum"]) if p.get("enum") else None,
                multi_segment=bool(p.get("multi_segment")),
            )
            for p in entry["params"]
        )
        ops[entry["operation_id"]] = Operation(
            operation_id=entry["operation_id"],
            service=entry["service"],
            method_name=entry["method_name"],
            http_method=entry["http_method"],
            path=entry["path"],
            summary=entry["summary"],
            description=entry["description"],
            tags=tuple(entry["tags"]),
            risk=entry["risk"],
            deprecated=entry["deprecated"],
            paginated=entry["paginated"],
            body_model=entry["body_model"],
            response_model=entry["response_model"],
            item_model=entry["item_model"],
            params=params,
        )
    return ops


def all_operations() -> list[Operation]:
    return list(_load().values())


def get_operation(operation_id: str) -> Operation:
    """Look up an operation by operationId, or ``service.method_name``."""
    ops = _load()
    if operation_id in ops:
        return ops[operation_id]
    if "." in operation_id:
        service, _, method = operation_id.partition(".")
        for op in ops.values():
            if op.service == service and op.method_name == method:
                return op
    raise KeyError(f"unknown operation {operation_id!r}")


_WORD = re.compile(r"[a-z0-9]+")
_SYNONYMS = {
    "device": "node",
    "app": "application",
    "list": "query",
    "show": "get",
    "fetch": "get",
    "tenant": "enterprise",
    "group": "project",
}


def _tokens(text: str) -> set[str]:
    words = _WORD.findall(re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower())
    out = set()
    for word in words:
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.add(_SYNONYMS.get(word, word))
    return out


@lru_cache(maxsize=1)
def _index() -> tuple[list[tuple[Operation, frozenset[str], frozenset[str]]], dict[str, float]]:
    rows = []
    doc_freq: dict[str, int] = {}
    for op in _load().values():
        name = op.operation_id.split("_", 1)[-1]
        head = frozenset(_tokens(" ".join([name, op.path, op.summary, op.method_name])))
        body = frozenset(_tokens(op.description + " " + " ".join(op.tags))) - head
        rows.append((op, head, body))
        for token in head | body:
            doc_freq[token] = doc_freq.get(token, 0) + 1
    total = len(rows)
    idf = {t: math.log(1 + total / n) for t, n in doc_freq.items()}
    return rows, idf


def search_operations(
    query: str,
    *,
    service: str | None = None,
    risk: Risk | None = None,
    limit: int = 20,
) -> list[Operation]:
    """Rank operations by relevance to a free-text ``query``.

    Terms are weighted by rarity (so "reboot" outweighs "edge"), and matches in
    the operation name, path, or summary count triple those in the description.
    Deprecated operations rank below equivalent live ones.
    """
    wanted = _tokens(query)
    if not wanted:
        return []
    rows, idf = _index()
    scored: list[tuple[float, Operation]] = []
    for op, head, body in rows:
        if (service and op.service != service) or (risk and op.risk != risk):
            continue
        score = sum(3 * idf[t] for t in wanted & head) + sum(idf[t] for t in wanted & body)
        if not score:
            continue
        # Prefer operations whose name is mostly about the query terms.
        score += 0.5 * score * len(wanted & head) / max(len(head), 1)
        if op.deprecated:
            score *= 0.8
        scored.append((score, op))
    scored.sort(key=lambda s: (-s[0], s[1].operation_id))
    return [op for _, op in scored[:limit]]


def model_for(name: str | None) -> Any:
    """Return the generated model class called ``name`` (or ``None``)."""
    if not name:
        return None
    from zedcloud._generated import models

    return getattr(models, name)
