#!/usr/bin/env python3
"""Generate the Zedcloud SDK models, services, and operation registry.

Usage::

    uv run python scripts/generate.py          # regenerate
    uv run python scripts/generate.py --check  # fail if output is stale (CI)

Inputs are the Swagger 2.0 specs in ``openapi/``. Outputs land in
``packages/zedcloud/src/zedcloud/_generated/``:

* ``models.py`` — one pydantic model per definition, shared across services.
  The specs repeat ~190 definitions verbatim, so they are merged (and checked
  for conflicts) instead of being emitted once per service.
* ``services/<ns>.py`` — a sync and an async class per service.
* ``operations.json`` — machine-readable registry of every operation, used by
  ``ZedcloudClient.call`` and the MCP server.

Design choices, all driven by how Zedcloud actually behaves:

* Response models are tolerant: every field is optional, unknown fields are
  kept (so GET → modify → PUT never drops data), enums accept values added
  server-side later, and spec ``pattern``/length constraints are not enforced.
  The spec marks fields ``required`` that list endpoints omit in practice; the
  server remains the source of truth for request validation.
* gRPC-gateway inlines the body schema of most update operations; those are
  hoisted into named ``<Method>Body`` models so updates are typed too.
"""

from __future__ import annotations

import argparse
import difflib
import json
import keyword
import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pydantic

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIR = ROOT / "openapi"
OUT_ROOT = ROOT / "packages" / "zedcloud" / "src" / "zedcloud" / "_generated"

# swagger stem -> (namespace attribute, class name, auth scheme)
SERVICES: dict[str, tuple[str, str, str]] = {
    "zedge_app_service": ("apps", "AppsService", "bearer"),
    "zedge_app_profile_service": ("app_profiles", "AppProfilesService", "bearer"),
    "zedge_diag_service": ("diag", "DiagService", "bearer"),
    "zedge_job_service": ("jobs", "JobsService", "bearer"),
    "zedge_kubernetes_service": ("k8s", "K8sService", "api_key"),
    "zedge_network_service": ("networks", "NetworksService", "bearer"),
    "zedge_node_cluster_service": ("node_clusters", "NodeClustersService", "bearer"),
    "zedge_node_service": ("nodes", "NodesService", "bearer"),
    "zedge_orchestration_service": ("orchestration", "OrchestrationService", "bearer"),
    "zedge_storage_service": ("storage", "StorageService", "bearer"),
    "zedge_user_service": ("iam", "IamService", "bearer"),
}

# operationId -> python method name, where the mechanical name is ambiguous
# or unreadable (numbered duplicates, copy-pasted operationIds, odd casing).
METHOD_OVERRIDES: dict[str, str] = {
    "CloudDiagnostics_checkClusterHealth": "check_cluster_health",
    "CloudDiagnostics_checkClusterHealth2": "get_cluster_health_ping",
    "EdgeDiagnostics_GetResourceMetricsTimeline": "get_events_resource_metrics_timeline",
    "EdgeDiagnostics_GetResourceMetricsTimeline2": "get_resource_metrics_timeline",
    "EdgeDiagnostics_GetTopUsers2": "get_top_users",
    "EdgeApplicationInstanceStatus_GetEdgeApplicationInstanceTrafficFlows2": (
        "get_edge_application_instance_traffic_flows_by_name"
    ),
    "EdgeApplicationInstanceStatus_GetEdgeApplicationInstanceTopTalkers2": (
        "get_edge_application_instance_top_talkers_by_name"
    ),
    "EdgeApplicationInstanceStatus_GetEdgeApplicationInstanceTrafficFlowsV22": (
        "get_edge_application_instance_traffic_flows_by_name_v2"
    ),
    "EdgeApplicationInstanceStatus_GetEdgeApplicationInstanceTopTalkersV22": (
        "get_edge_application_instance_top_talkers_by_name_v2"
    ),
    "EdgeApplicationInstanceConfiguration_UpdatePatchEnvelopeReferencetoAppInstanceV2": (
        "update_patch_envelope_reference_to_app_instance_v2"
    ),
    "PatchEnvelopeConfiguration_DeleteAppInstanceSnapshot": "delete_patch_envelope",
    "EdgeNodeConfiguration_UpdateEdgeNodeBaseOS2": "publish_edge_node_base_os",
    "EdgeNodeConfiguration_UpdateEdgeNodeBaseOS3": "unpublish_edge_node_base_os",
    "HardwareModel_DeleteEdgeNode": "delete_pcr_template",
    "ResourceGroup_GetDeploymentListbyIdv2": "get_deployment_list_by_id_v2",
    "ImageConfiguration_MarkEveImageLatest2": "mark_eve_image_latest_for_hw_class",
    "IdentityAccessManagement_UpdateEnterprise": "update_self_enterprise",
    "IdentityAccessManagement_UpdateEnterprise2": "update_enterprise",
    "IdentityAccessManagement_UpdateUser": "update_self_user",
    "IdentityAccessManagement_UpdateUser2": "update_user",
    "IdentityAccessManagement_GetUserSession": "get_user_session_by_token",
    "IdentityAccessManagement_GetUserSession2": "get_user_session_token",
    "KubernetesDashboard_ProxyKubernetesRequest": "proxy_kubernetes_get",
    "KubernetesDashboard_ProxyKubernetesRequest2": "proxy_kubernetes_post",
    "KubernetesDashboard_ProxyKubernetesRequest3": "proxy_kubernetes_put",
    "KubernetesDashboard_ProxyKubernetesRequest4": "proxy_kubernetes_patch",
    "KubernetesDashboard_ProxyKubernetesRequest5": "proxy_kubernetes_delete",
}

# Mechanical snake_case artifacts to repair in every method name.
NAME_FIXUPS = (("de_activate", "deactivate"), ("ce_ps", "ceps"), ("_o_s_", "_os_"))

# Path parameters whose values are multi-segment paths (``/`` preserved).
MULTI_SEGMENT_PARAMS = {("k8s", "path")}

# Last literal path segment of a PUT/POST that makes the operation destructive.
DESTRUCTIVE_ACTIONS = frozenset(
    {
        "deactivate",
        "offboard",
        "preparepoweroff",
        "purge",
        "reboot",
        "restart",
        "restore",
        "unpublish",
        "upgrade",
        "k3s-upgrade",
        "disable",
    }
)

PAGINATION_PARAMS = {
    "next.pageToken": "page_token",
    "next.pageNum": "page_num",
    "next.pageSize": "page_size",
    "next.orderBy": "order_by",
}
# Response-side cursor field that the specs leak into request parameters.
DROPPED_PARAMS = {"next.totalPages"}

HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# Identifiers used in generated annotations; fields may not shadow them.
ANNOTATION_NAMES = {"str", "int", "float", "bool"}
# Attributes of pydantic.BaseModel (and ZedcloudModel) that fields must not shadow.
PYDANTIC_RESERVED = {n for n in dir(pydantic.BaseModel) if not n.startswith("_")} | {"to_api"}
MODULE_RESERVED = {"OpenEnum", "ZedcloudModel", "Timestamp", "Field"}


# --------------------------------------------------------------------------- naming


def snake(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"_+", "_", name).strip("_").lower()


def pascal(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[^0-9a-zA-Z]+", name) if p)


def method_name(operation_id: str) -> str:
    if operation_id in METHOD_OVERRIDES:
        return METHOD_OVERRIDES[operation_id]
    rest = operation_id.split("_", 1)[1] if "_" in operation_id else operation_id
    name = snake(rest)
    for old, new in NAME_FIXUPS:
        name = name.replace(old, new)
    return name


def field_name(prop: str, taken: set[str]) -> str:
    name = snake(prop) or "field"
    if name[0].isdigit():
        name = f"f_{name}"
    if keyword.iskeyword(name) or name in PYDANTIC_RESERVED or name in ANNOTATION_NAMES:
        name += "_"
    base, n = name, 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1
    taken.add(name)
    return name


def enum_member(value: str, taken: set[str]) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", str(value)).strip("_").upper() or "EMPTY"
    if name[0].isdigit():
        name = f"V_{name}"
    base, n = name, 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1
    taken.add(name)
    return name


def pystr(text: str) -> str:
    """Render ``text`` as a Python string literal."""
    return json.dumps(text, ensure_ascii=False)


def docstring(lines: list[str], indent: str) -> list[str]:
    body = "\n".join(lines).strip().replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    if not body:
        return []
    out = body.splitlines()
    if len(out) == 1:
        return [f'{indent}"""{out[0]}"""']
    return [f'{indent}"""{out[0]}', *[f"{indent}{ln}".rstrip() for ln in out[1:]], f'{indent}"""']


def wrap(text: str, width: int = 88) -> list[str]:
    out: list[str] = []
    for para in text.strip().splitlines():
        para = para.strip()
        out.extend(textwrap.wrap(para, width) if para else [""])
    return out


def describe(schema: dict[str, Any]) -> str:
    parts = [schema.get("title") or "", schema.get("description") or ""]
    text = " — ".join(p.strip().rstrip(".") for p in parts if p and p.strip())
    return re.sub(r"\s+", " ", text)


# --------------------------------------------------------------------------- loading


@dataclass
class Param:
    name: str  # wire name
    py: str  # python argument name
    location: str  # path | query | header | body
    type: str  # python annotation
    required: bool
    description: str
    enum: list[str] | None = None
    multi_segment: bool = False


@dataclass
class Operation:
    ns: str
    operation_id: str
    method: str
    path: str
    py: str
    summary: str
    description: str
    tags: list[str]
    params: list[Param] = field(default_factory=list)
    body_model: str | None = None
    response_model: str | None = None
    item_model: str | None = None  # paginated item type
    iter_name: str | None = None
    risk: str = "read"
    deprecated: bool = False
    lookup: tuple[str, str] | None = None  # (lookup method name, by-name method name)

    @property
    def paginated(self) -> bool:
        return self.item_model is not None


class Generator:
    def __init__(self) -> None:
        self.definitions: dict[str, dict[str, Any]] = {}
        self.class_names: dict[str, str] = {}  # definition name -> class name
        self.operations: list[Operation] = []
        self.infos: dict[str, dict[str, Any]] = {}

    # -- specs

    def load(self) -> None:
        origins: dict[str, str] = {}
        for stem in sorted(SERVICES):
            spec_path = OPENAPI_DIR / f"{stem}.swagger.json"
            spec = json.loads(spec_path.read_text())
            ns = SERVICES[stem][0]
            self.infos[ns] = spec.get("info") or {}
            for name, schema in (spec.get("definitions") or {}).items():
                if name in self.definitions and self.definitions[name] != schema:
                    raise SystemExit(
                        f"definition {name!r} differs between {origins[name]} and {stem}"
                    )
                self.definitions[name] = schema
                origins[name] = stem
            self._load_operations(ns, spec)
        for name in self.definitions:
            self._register_class(name, pascal(name))

    def _register_class(self, definition: str, class_name: str) -> str:
        if class_name in MODULE_RESERVED or class_name in self.class_names.values():
            raise SystemExit(f"class name collision: {class_name} ({definition})")
        self.class_names[definition] = class_name
        return class_name

    def _load_operations(self, ns: str, spec: dict[str, Any]) -> None:
        seen: dict[str, str] = {}
        for path, item in (spec.get("paths") or {}).items():
            shared = item.get("parameters") or []
            for method in HTTP_METHODS:
                raw = item.get(method)
                if not raw:
                    continue
                op = Operation(
                    ns=ns,
                    operation_id=raw["operationId"],
                    method=method.upper(),
                    path=path,
                    py=method_name(raw["operationId"]),
                    summary=(raw.get("summary") or "").strip(),
                    description=(raw.get("description") or "").strip(),
                    tags=list(raw.get("tags") or []),
                    deprecated=bool(raw.get("deprecated")),
                )
                if op.py in seen:
                    raise SystemExit(
                        f"{ns}: method name {op.py!r} used by {seen[op.py]} and "
                        f"{op.operation_id}; add a METHOD_OVERRIDES entry"
                    )
                seen[op.py] = op.operation_id
                self._load_params(op, [*shared, *(raw.get("parameters") or [])])
                op.response_model = self._response_model(raw)
                op.risk = classify_risk(op)
                self.operations.append(op)

    def _load_params(self, op: Operation, raw_params: list[dict[str, Any]]) -> None:
        taken = {"self", "body"}
        for raw in raw_params:
            where = raw.get("in")
            wire = raw["name"]
            if wire in DROPPED_PARAMS:
                continue
            if where == "body":
                op.body_model = self._body_model(op, raw.get("schema") or {})
                op.params.append(
                    Param(
                        name="body",
                        py="body",
                        location="body",
                        type=op.body_model or "Any",
                        required=bool(raw.get("required", True)),
                        description=describe(raw),
                    )
                )
                continue
            if where == "formData":
                op.params.append(
                    Param(
                        name=wire,
                        py=snake(wire),
                        location="form",
                        type="FileContent",
                        required=bool(raw.get("required")),
                        description=describe(raw) or "File to upload.",
                    )
                )
                taken.add(snake(wire))
                continue
            if where == "header" and wire.lower() == "x-request-id":
                continue  # supplied automatically; see request_id kwarg
            py = PAGINATION_PARAMS.get(wire) or snake(wire)
            if keyword.iskeyword(py):
                py += "_"
            if py in taken:
                py = f"{py}_{where}"
            taken.add(py)
            op.params.append(
                Param(
                    name=wire,
                    py=py,
                    location=where,
                    type=param_type(raw),
                    required=where == "path" or bool(raw.get("required")),
                    description=describe(raw),
                    enum=(raw.get("items") or {}).get("enum") or raw.get("enum"),
                    multi_segment=(op.ns, wire) in MULTI_SEGMENT_PARAMS,
                )
            )

    def _body_model(self, op: Operation, schema: dict[str, Any]) -> str | None:
        ref = schema.get("$ref")
        if ref:
            return ref.rsplit("/", 1)[-1]
        if schema.get("type") == "object" and schema.get("properties"):
            name = pascal(op.py) + "Body"
            if name in self.definitions or name in self.class_names.values():
                name = pascal(op.ns) + name
            self.definitions[name] = schema
            return name
        return None

    def _response_model(self, raw: dict[str, Any]) -> str | None:
        for code in ("200", "201", "202"):
            schema = (raw.get("responses", {}).get(code) or {}).get("schema") or {}
            if "$ref" in schema:
                return schema["$ref"].rsplit("/", 1)[-1]
        return None

    def link_pagination(self) -> None:
        for op in self.operations:
            if not any(p.name == "next.pageSize" for p in op.params) or not op.response_model:
                continue
            items = (self.definitions[op.response_model].get("properties") or {}).get("list")
            ref = ((items or {}).get("items") or {}).get("$ref")
            if items and items.get("type") == "array" and ref:
                op.item_model = ref.rsplit("/", 1)[-1]
        taken = {(op.ns, op.py) for op in self.operations}
        for op in self.operations:
            if not op.item_model:
                continue
            stem = next(
                (op.py[len(p) :] for p in ("query_", "get_", "list_") if op.py.startswith(p)), op.py
            )
            name = f"iter_{stem}"
            if (op.ns, name) in taken:
                name = f"iter_{op.py}"
            if (op.ns, name) in taken:
                raise SystemExit(f"{op.ns}: iterator name {name!r} collides")
            taken.add((op.ns, name))
            op.iter_name = name

    def link_lookups(self) -> None:
        """Pair ``…/id/{id}…`` GETs with their ``…/name/{name}…`` twins.

        Each pair yields a ``lookup_*`` method that accepts either identifier.
        """
        by_key = {(op.ns, op.path): op for op in self.operations if op.method == "GET"}
        taken = {(op.ns, op.py) for op in self.operations}
        for op in self.operations:
            if op.method != "GET" or "/id/{id}" not in op.path or op.path.startswith("/v2/"):
                continue
            if [p.name for p in op.params if p.location == "path"] != ["id"]:
                continue
            twin = by_key.get((op.ns, op.path.replace("/id/{id}", "/name/{name}", 1)))
            if not twin or twin.response_model != op.response_model:
                continue
            if any(p.required for p in op.params if p.location == "query"):
                continue
            if not op.py.startswith("get_"):
                continue
            name = "lookup_" + op.py[len("get_") :].removesuffix("_by_id")
            if (op.ns, name) in taken:
                continue
            taken.add((op.ns, name))
            op.lookup = (name, twin.py)

    # -- models

    def cls(self, definition: str) -> str:
        return self.class_names[definition]

    def annotation(self, schema: dict[str, Any], owner: str, prop: str) -> str:
        if "$ref" in schema:
            return self.cls(schema["$ref"].rsplit("/", 1)[-1])
        kind = schema.get("type")
        fmt = schema.get("format") or ""
        if kind == "string":
            if fmt == "date-time":
                return "Timestamp"
            if fmt in {"int64", "uint64", "int32", "uint32"}:
                return "int"
            if schema.get("enum"):
                return self._inline_enum(schema, owner, prop)
            return "str"
        if kind == "integer":
            return "int"
        if kind == "number":
            return "int" if fmt.startswith(("int", "uint")) else "float"
        if kind == "boolean":
            return "bool"
        if kind == "array":
            inner = self.annotation(schema.get("items") or {}, owner, prop)
            return f"_t.List[{inner}]"
        if kind == "object" or "additionalProperties" in schema or "properties" in schema:
            if schema.get("properties"):
                return self._inline_model(schema, owner, prop)
            extra = schema.get("additionalProperties")
            if isinstance(extra, dict) and extra:
                return f"_t.Dict[str, {self.annotation(extra, owner, prop)}]"
            return "_t.Dict[str, _t.Any]"
        return "_t.Any"

    def _inline_model(self, schema: dict[str, Any], owner: str, prop: str) -> str:
        name = owner + pascal(prop)
        if name not in self.class_names.values():
            self.definitions[name] = schema
            self._register_class(name, name)
            self._pending.append(name)
        return name

    def _inline_enum(self, schema: dict[str, Any], owner: str, prop: str) -> str:
        return self._inline_model(schema, owner, prop)

    def render_models(self) -> str:
        out = [
            "# Generated by scripts/generate.py from openapi/*.swagger.json. Do not edit.",
            '"""Pydantic models for every Zedcloud API definition."""',
            "",
            "from __future__ import annotations",
            "",
            "import typing as _t",
            "",
            "from pydantic import Field",
            "",
            "from zedcloud._base import OpenEnum, Timestamp, ZedcloudModel",
            "",
        ]
        exported: list[str] = []
        self._pending = sorted(self.definitions, key=lambda d: self.cls(d))
        rendered: set[str] = set()
        while self._pending:
            definition = self._pending.pop(0)
            if definition in rendered:
                continue
            rendered.add(definition)
            schema = self.definitions[definition]
            name = self.cls(definition)
            exported.append(name)
            out.append("")
            if schema.get("enum"):
                out.extend(self._render_enum(name, schema))
            else:
                out.extend(self._render_model(name, schema))
        out += ["", "", "__all__ = ["]
        out += [f"    {pystr(n)}," for n in sorted(exported)]
        out.append("]")
        return "\n".join(out) + "\n"

    def _render_enum(self, name: str, schema: dict[str, Any]) -> list[str]:
        lines = [f"class {name}(OpenEnum):"]
        lines += docstring(wrap(describe(schema) or f"{name} values."), "    ")
        taken: set[str] = set()
        for value in schema["enum"]:
            lines.append(f"    {enum_member(value, taken)} = {pystr(str(value))}")
        return ["", *lines]

    def _render_model(self, name: str, schema: dict[str, Any]) -> list[str]:
        lines = [f"class {name}(ZedcloudModel):"]
        doc = wrap(describe(schema) or f"{name}.")
        required = schema.get("required") or []
        if isinstance(required, list) and required and required != ["true"]:
            doc += ["", "Required by the API spec when sending: " + ", ".join(required) + "."]
        lines += docstring(doc, "    ")
        props = schema.get("properties") or {}
        taken: set[str] = set()
        for prop, prop_schema in props.items():
            py = field_name(prop, taken)
            ann = self.annotation(prop_schema, name, prop)
            desc = describe(prop_schema)
            if prop_schema.get("readOnly"):
                desc = f"{desc} (read-only)".strip()
            args = ["default=None"]
            if py != prop:
                args.append(f"alias={pystr(prop)}")
            if desc:
                args.append(f"description={pystr(desc)}")
            lines.append(f"    {py}: {ann} | None = Field({', '.join(args)})")
        return ["", *lines]

    # -- services

    def render_service(self, ns: str, class_name: str, security: str) -> str:
        ops = [op for op in self.operations if op.ns == ns]
        models = sorted(
            {
                self.cls(m)
                for op in ops
                for m in (op.body_model, op.response_model, op.item_model)
                if m
            }
        )
        title = self.infos[ns].get("title") or ns
        out = [
            "# Generated by scripts/generate.py from openapi/*.swagger.json. Do not edit.",
            f'"""{title} — generated sync and async clients."""',
            "",
            "from __future__ import annotations",
            "",
            "import typing as _t",
            "from collections.abc import AsyncIterator, Iterator, Mapping, Sequence",
            "",
            "from zedcloud._service import AsyncBaseService, BaseService, FileContent",
        ]
        if models:
            out.append("from zedcloud._generated.models import (")
            out += [f"    {m}," for m in models]
            out.append(")")
        for is_async in (False, True):
            prefix = "Async" if is_async else ""
            base = "AsyncBaseService" if is_async else "BaseService"
            out += ["", "", f"class {prefix}{class_name}({base}):"]
            out += docstring([f"{title} ({'async' if is_async else 'sync'})."], "    ")
            out += ["", f'    _security = "{security}"']
            for op in ops:
                out.append("")
                out.extend(self._render_method(op, is_async))
                if op.paginated:
                    out.append("")
                    out.extend(self._render_iterator(op, is_async))
                if op.lookup:
                    out.append("")
                    out.extend(self._render_lookup(op, is_async))
        return "\n".join(out) + "\n"

    def _signature(self, op: Operation, *, for_iter: bool = False) -> list[str]:
        positional = [p for p in op.params if p.location in ("path", "form")]
        body = [p for p in op.params if p.location == "body"]
        rest = [p for p in op.params if p.location in ("query", "header")]
        if for_iter:
            rest = [p for p in rest if p.name not in PAGINATION_PARAMS or p.py == "order_by"]
        parts = ["self"]
        for p in positional:
            parts.append(f"{p.py}: {p.type}")
        for p in body:
            ann = f"{self.cls(p.type)} | Mapping[str, _t.Any]" if op.body_model else "_t.Any"
            parts.append(f"body: {ann}" if p.required else f"body: {ann} | None = None")
        parts.append("*")
        for p in rest:
            if p.required:
                parts.append(f"{p.py}: {p.type}")
        for p in rest:
            if not p.required:
                parts.append(f"{p.py}: {p.type} | None = None")
        if for_iter:
            parts += ["page_size: int = 100", "max_items: int | None = None"]
        parts.append("request_id: str | None = None")
        return parts

    def _doc(self, op: Operation, *, for_iter: bool = False) -> list[str]:
        lines = wrap(op.summary or op.operation_id)
        if for_iter:
            lines = [f"Iterate over every result of :meth:`{op.py}`, fetching pages lazily."]
        elif op.description and op.description.rstrip(".") != op.summary.rstrip("."):
            lines += ["", *wrap(op.description)]
        if op.deprecated:
            lines += ["", ".. deprecated:: Marked deprecated in the API spec."]
        args = [p for p in op.params if p.description or p.enum]
        if for_iter:
            args = [p for p in args if p.name not in PAGINATION_PARAMS]
        if args or for_iter:
            lines += ["", "Args:"]
            for p in args:
                text = p.description or ""
                if p.enum:
                    text = (text + " One of: " + ", ".join(map(str, p.enum)) + ".").strip()
                wrapped = wrap(text, 80)
                lines.append(f"    {p.py}: {wrapped[0] if wrapped else ''}")
                lines += [f"        {w}" for w in wrapped[1:]]
            if for_iter:
                lines.append("    page_size: Items requested per page.")
                lines.append("    max_items: Stop after yielding this many items.")
        risk = {"read": "read-only", "write": "modifies state", "destructive": "DESTRUCTIVE"}
        lines += [
            "",
            f"``{op.method} {op.path}`` · operationId ``{op.operation_id}`` · {risk[op.risk]}",
        ]
        return docstring(lines, "        ")

    def _call_args(self, op: Operation) -> list[str]:
        path_params = [p for p in op.params if p.location == "path"]
        query = [p for p in op.params if p.location == "query"]
        headers = [p for p in op.params if p.location == "header"]
        args = [pystr(op.method), pystr(op.path)]
        if path_params:
            args.append("path={" + ", ".join(f"{pystr(p.name)}: {p.py}" for p in path_params) + "}")
            multi = [p.name for p in path_params if p.multi_segment]
            if multi:
                args.append("multi_segment={" + ", ".join(pystr(m) for m in multi) + "}")
        if query:
            args.append("query={" + ", ".join(f"{pystr(p.name)}: {p.py}" for p in query) + "}")
        if headers:
            args.append("headers={" + ", ".join(f"{pystr(p.name)}: {p.py}" for p in headers) + "}")
        form = [p for p in op.params if p.location == "form"]
        if form:
            args.append("files={" + ", ".join(f"{pystr(p.name)}: {p.py}" for p in form) + "}")
        if any(p.location == "body" for p in op.params):
            args.append("body=body")
        if op.response_model:
            args.append(f"response_model={self.cls(op.response_model)}")
        args.append("request_id=request_id")
        args.append(f"operation_id={pystr(op.operation_id)}")
        return args

    def _render_method(self, op: Operation, is_async: bool) -> list[str]:
        ret = self.cls(op.response_model) if op.response_model else "_t.Any"
        sig = ",\n        ".join(self._signature(op))
        kw = "async def" if is_async else "def"
        aw = "await " if is_async else ""
        lines = [f"    {kw} {op.py}(\n        {sig},\n    ) -> {ret}:"]
        lines += self._doc(op)
        call = ",\n            ".join(self._call_args(op))
        lines.append(f"        return {aw}self._request(\n            {call},\n        )")
        return lines

    def _render_iterator(self, op: Operation, is_async: bool) -> list[str]:
        item = self.cls(op.item_model or "")
        name = op.iter_name
        sig = ",\n        ".join(self._signature(op, for_iter=True))
        forwarded = [
            p
            for p in op.params
            if p.location in ("path", "query", "header", "body")
            and (p.name not in PAGINATION_PARAMS or p.py == "order_by")
        ]
        fwd = ", ".join(f"{p.py}={p.py}" for p in forwarded)
        ret = f"AsyncIterator[{item}]" if is_async else f"Iterator[{item}]"
        lines = [f"    def {name}(\n        {sig},\n    ) -> {ret}:"]
        lines += self._doc(op, for_iter=True)
        lines.append(
            f"        return self._paginate(\n"
            f"            self.{op.py},\n"
            f"            page_size=page_size,\n"
            f"            max_items=max_items,\n"
            f"            request_id=request_id,\n"
            + (f"            {fwd},\n" if fwd else "")
            + "        )"
        )
        return lines

    def _render_lookup(self, op: Operation, is_async: bool) -> list[str]:
        name, by_name = op.lookup or ("", "")
        ret = self.cls(op.response_model) if op.response_model else "_t.Any"
        kw, aw = ("async def", "await ") if is_async else ("def", "")
        lines = [
            f"    {kw} {name}(self, name_or_id: str, *, request_id: str | None = None) -> {ret}:",
            *docstring(
                [
                    f"{op.summary or op.py}, by name or ID.",
                    "",
                    f"UUID-shaped values call :meth:`{op.py}` (falling back to :meth:`{by_name}`",
                    f"if no object has that ID); anything else calls :meth:`{by_name}`.",
                ],
                "        ",
            ),
            f"        return {aw}self._lookup(",
            f"            self.{op.py}, self.{by_name}, name_or_id, request_id=request_id",
            "        )",
        ]
        return lines

    # -- registry

    def render_registry(self) -> str:
        entries = []
        for op in self.operations:
            entries.append(
                {
                    "operation_id": op.operation_id,
                    "service": op.ns,
                    "method_name": op.py,
                    "http_method": op.method,
                    "path": op.path,
                    "summary": op.summary,
                    "description": op.description,
                    "tags": op.tags,
                    "risk": op.risk,
                    "deprecated": op.deprecated,
                    "paginated": op.paginated,
                    "body_model": self.cls(op.body_model) if op.body_model else None,
                    "response_model": self.cls(op.response_model) if op.response_model else None,
                    "item_model": self.cls(op.item_model) if op.item_model else None,
                    "params": [
                        {
                            "name": p.name,
                            "python_name": p.py,
                            "in": p.location,
                            "type": p.type,
                            "required": p.required,
                            "description": p.description,
                            **({"enum": p.enum} if p.enum else {}),
                            **({"multi_segment": True} if p.multi_segment else {}),
                        }
                        for p in op.params
                    ],
                }
            )
        return json.dumps({"operations": entries}, indent=0, ensure_ascii=False) + "\n"


def param_type(raw: dict[str, Any]) -> str:
    kind = raw.get("type")
    fmt = raw.get("format") or ""
    scalar = {"string": "str", "integer": "int", "boolean": "bool"}
    if kind == "array":
        inner = (raw.get("items") or {}).get("type", "string")
        return f"Sequence[{scalar.get(inner, 'float' if inner == 'number' else '_t.Any')}]"
    if kind == "number":
        return "int" if fmt.startswith(("int", "uint")) else "float"
    if kind == "string" and fmt in {"int64", "uint64", "int32", "uint32"}:
        return "int | str"
    return scalar.get(kind or "string", "_t.Any")


def classify_risk(op: Operation) -> str:
    if op.method == "GET":
        return "read"
    if op.method == "DELETE":
        return "destructive"
    literal = [s for s in op.path.split("/") if s and not s.startswith("{")]
    if literal and literal[-1].lower() in DESTRUCTIVE_ACTIONS:
        return "destructive"
    return "write"


# --------------------------------------------------------------------------- output


def build() -> dict[str, str]:
    gen = Generator()
    gen.load()
    gen.link_pagination()
    gen.link_lookups()
    files: dict[str, str] = {
        "__init__.py": '"""Generated from openapi/*.swagger.json by scripts/generate.py."""\n',
        "services/__init__.py": '"""Generated service clients."""\n',
    }
    files["models.py"] = gen.render_models()
    for ns, class_name, security in SERVICES.values():
        files[f"services/{ns}.py"] = gen.render_service(ns, class_name, security)
    files["operations.json"] = gen.render_registry()
    return format_python(files)


def format_python(files: dict[str, str]) -> dict[str, str]:
    """Run ruff format so output is stable and readable."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for rel, text in files.items():
            dest = base / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)
        subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--quiet", "--line-length", "100", str(base)],
            check=True,
        )
        return {rel: (base / rel).read_text() for rel in files}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if generated code is stale")
    args = parser.parse_args()
    files = build()
    if args.check:
        stale = []
        for rel, text in files.items():
            path = OUT_ROOT / rel
            current = path.read_text() if path.exists() else ""
            if current != text:
                stale.append(rel)
                diff = difflib.unified_diff(
                    current.splitlines(), text.splitlines(), f"a/{rel}", f"b/{rel}", lineterm=""
                )
                print("\n".join(list(diff)[:40]), file=sys.stderr)
        existing = {str(p.relative_to(OUT_ROOT)) for p in OUT_ROOT.rglob("*") if p.is_file()}
        extra = sorted(existing - set(files) - {p for p in existing if "__pycache__" in p})
        if stale or extra:
            print(f"generated code is stale: {stale + extra}", file=sys.stderr)
            print("run: uv run python scripts/generate.py", file=sys.stderr)
            return 1
        print("generated code is up to date")
        return 0
    if OUT_ROOT.exists():
        for path in sorted(OUT_ROOT.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    for rel, text in files.items():
        dest = OUT_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    ops = json.loads(files["operations.json"])["operations"]
    print(f"generated {len(ops)} operations into {OUT_ROOT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
