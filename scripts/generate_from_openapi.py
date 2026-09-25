#!/usr/bin/env python3
"""Regenerate Zedcloud SDK models and service wrappers from OpenAPI swagger specs.

Usage:
    uv run python scripts/generate_from_openapi.py
    make generate

Reads ``openapi/*.swagger.json`` (OpenAPI 2.0) and writes:

* ``packages/zedcloud/src/zedcloud/_generated/models/<ns>.py``
* ``packages/zedcloud/src/zedcloud/_generated/services/<ns>.py``
"""

from __future__ import annotations

import json
import keyword
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIR = ROOT / "openapi"
OUT_ROOT = ROOT / "packages" / "zedcloud" / "src" / "zedcloud" / "_generated"
MODELS_DIR = OUT_ROOT / "models"
SERVICES_DIR = OUT_ROOT / "services"

SERVICE_MAP: dict[str, tuple[str, str]] = {
    # swagger stem -> (python namespace, ServiceClassName)
    "zedge_app_service": ("apps", "AppsService"),
    "zedge_node_service": ("nodes", "NodesService"),
    "zedge_user_service": ("iam", "IamService"),
    "zedge_orchestration_service": ("orchestration", "OrchestrationService"),
    "zedge_kubernetes_service": ("k8s", "K8sService"),
    "zedge_storage_service": ("storage", "StorageService"),
    "zedge_diag_service": ("diag", "DiagService"),
    "zedge_app_profile_service": ("app_profiles", "AppProfilesService"),
    "zedge_network_service": ("networks", "NetworksService"),
    "zedge_job_service": ("jobs", "JobsService"),
    "zedge_node_cluster_service": ("node_clusters", "NodeClustersService"),
}

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head"})


def main() -> int:
    if not OPENAPI_DIR.is_dir():
        print(f"error: openapi directory missing: {OPENAPI_DIR}", file=sys.stderr)
        return 1

    specs = sorted(OPENAPI_DIR.glob("*.swagger.json"))
    if not specs:
        print(f"error: no swagger files in {OPENAPI_DIR}", file=sys.stderr)
        return 1

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    MODELS_DIR.mkdir(parents=True)
    SERVICES_DIR.mkdir(parents=True)

    (OUT_ROOT / "__init__.py").write_text(
        '"""Auto-generated from openapi/*.swagger.json — do not edit by hand."""\n'
    )
    (MODELS_DIR / "__init__.py").write_text(
        '"""Generated Pydantic models per Zedcloud service."""\n'
    )
    (SERVICES_DIR / "__init__.py").write_text(
        '"""Generated service wrappers per Zedcloud service."""\n'
    )

    for spec_path in specs:
        stem = spec_path.name.replace(".swagger.json", "")
        if stem not in SERVICE_MAP:
            print(f"warning: skipping unmapped spec {spec_path.name}", file=sys.stderr)
            continue
        ns, class_name = SERVICE_MAP[stem]
        print(f"generating {ns} from {spec_path.name} …")
        swagger = json.loads(spec_path.read_text())
        generate_models(swagger, ns, spec_path.name)
        generate_service(swagger, ns, class_name)

    write_models_all()
    print(f"done → {OUT_ROOT.relative_to(ROOT)}")
    return 0


def swagger_to_oa3_schemas(swagger: dict[str, Any]) -> dict[str, Any]:
    """Convert Swagger 2.0 ``definitions`` into an OpenAPI 3 schemas-only document."""
    definitions = swagger.get("definitions") or {}
    schemas = json.loads(json.dumps(definitions))  # deep copy
    _rewrite_refs(schemas)
    _sanitize_patterns(schemas)
    return {
        "openapi": "3.0.3",
        "info": swagger.get("info") or {"title": "zedcloud", "version": "1.0"},
        "paths": {},
        "components": {"schemas": schemas},
    }


def _sanitize_patterns(obj: Any) -> None:
    """Drop or repair invalid JSON Schema ``pattern`` values (broken UUID regexes)."""
    if isinstance(obj, dict):
        pattern = obj.get("pattern")
        if isinstance(pattern, str):
            fixed = _fix_regex_pattern(pattern)
            if fixed is None:
                obj.pop("pattern", None)
            elif fixed != pattern:
                obj["pattern"] = fixed
        for value in obj.values():
            _sanitize_patterns(value)
    elif isinstance(obj, list):
        for item in obj:
            _sanitize_patterns(item)


def _fix_regex_pattern(pattern: str) -> str | None:
    # Common swagger truncation: UUID pattern missing the final '}'
    if pattern.endswith("{12"):
        pattern = pattern + "}"
    try:
        re.compile(pattern)
    except re.error:
        return None
    return pattern


def _rewrite_refs(obj: Any) -> None:
    if isinstance(obj, dict):
        # Property-level ``required: ["true"]`` is invalid JSON Schema — drop it.
        if (
            "required" in obj
            and isinstance(obj["required"], list)
            and (obj["required"] == ["true"] or obj["required"] == [True])
        ):
            obj.pop("required", None)
        # Swagger often emits ``type`` / other keywords alongside ``$ref``.
        # Keep a pure reference so generators resolve enums (e.g. Origin).
        if "$ref" in obj and isinstance(obj["$ref"], str):
            ref = obj["$ref"]
            if ref.startswith("#/definitions/"):
                ref = "#/components/schemas/" + ref.rsplit("/", 1)[-1]
            obj.clear()
            obj["$ref"] = ref
            # Do not recurse into $ref-only dicts.
            continue_children = False
        else:
            continue_children = True
        if continue_children:
            for value in list(obj.values()):
                _rewrite_refs(value)
        return
    if isinstance(obj, list):
        for item in obj:
            _rewrite_refs(item)


def generate_models(swagger: dict[str, Any], ns: str, source_name: str) -> None:
    oa3 = swagger_to_oa3_schemas(swagger)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        input_path = tmp_path / f"{ns}.oa3.json"
        output_path = tmp_path / f"{ns}.py"
        input_path.write_text(json.dumps(oa3))
        cmd = [
            sys.executable,
            "-m",
            "datamodel_code_generator",
            "--input",
            str(input_path),
            "--input-file-type",
            "openapi",
            "--output",
            str(output_path),
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--use-standard-collections",
            "--use-union-operator",
            "--target-python-version",
            "3.10",
            "--snake-case-field",
            "--use-default-kwarg",
            "--collapse-root-models",
            "--formatters",
            "ruff-format",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            raise SystemExit(f"datamodel-code-generator failed for {ns}")
        body = output_path.read_text()
        # Soften noisy FutureWarnings by pinning a header.
        header = (
            f"# Generated by scripts/generate_from_openapi.py from {source_name}\n"
            f"# Do not edit by hand — re-run: uv run python scripts/generate_from_openapi.py\n\n"
        )
        # Strip the default datamodel header timestamp block's first comment lines if present
        if body.startswith("# generated by datamodel-codegen:"):
            lines = body.splitlines(keepends=True)
            # keep everything after the blank line following the header comments
            idx = 0
            while idx < len(lines) and (lines[idx].startswith("#") or lines[idx].strip() == ""):
                idx += 1
            body = "".join(lines[idx:])
        dest = MODELS_DIR / f"{ns}.py"
        dest.write_text(header + body)


def camel_to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def operation_method_name(operation_id: str) -> str:
    rest = operation_id.split("_", 1)[1] if "_" in operation_id else operation_id
    return camel_to_snake(rest)


def safe_ident(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", name)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"p_{cleaned}"
    if not cleaned:
        cleaned = "param"
    if keyword.iskeyword(cleaned):
        cleaned = f"{cleaned}_"
    return cleaned


def param_py_name(swagger_name: str) -> str:
    # next.pageToken -> next_page_token; X-Request-Id -> request_id
    if swagger_name.lower() in {"x-request-id", "x_request_id"}:
        return "request_id"
    if swagger_name.lower() in {"content-range", "content_range"}:
        return "content_range"
    # Normalize separators before camel→snake so "Content-Range" → content_range
    normalized = swagger_name.replace(".", "_").replace("-", "_")
    return safe_ident(camel_to_snake(normalized))


def schema_ref_name(schema: dict[str, Any] | None) -> str | None:
    if not schema:
        return None
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/definitions/"):
        return python_model_name(ref.rsplit("/", 1)[-1])
    # inline
    if schema.get("type") == "array":
        return None
    return None


def python_model_name(definition_name: str) -> str:
    """Match datamodel-code-generator class naming (underscores stripped)."""
    return definition_name.replace("_", "")


def python_type_for_param(param: dict[str, Any]) -> str:
    if param.get("in") == "body":
        ref = schema_ref_name(param.get("schema") or {})
        if ref:
            return f"{ref} | dict[str, Any]"
        return "dict[str, Any] | Any"
    ptype = param.get("type")
    if ptype == "array":
        items = param.get("items") or {}
        item_type = items.get("type", "string")
        inner = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
        }.get(item_type, "Any")
        return f"list[{inner}]"
    return {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "file": "Any",
    }.get(ptype or "string", "Any")


def response_model_name(op: dict[str, Any]) -> str | None:
    responses = op.get("responses") or {}
    for code in ("200", "201", "202"):
        if code in responses:
            schema = (responses[code] or {}).get("schema") or {}
            return schema_ref_name(schema)
    # some delete ops return ZsrvResponse under 200 already covered
    for code, resp in responses.items():
        if str(code).startswith("2"):
            schema = (resp or {}).get("schema") or {}
            name = schema_ref_name(schema)
            if name:
                return name
    return None


def collect_operations(swagger: dict[str, Any]) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    for path, item in (swagger.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method not in HTTP_METHODS or not isinstance(op, dict):
                continue
            operation_id = op.get("operationId") or f"{method}_{path}"
            ops.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": operation_id,
                    "summary": (op.get("summary") or "").strip(),
                    "description": (op.get("description") or "").strip(),
                    "parameters": list(op.get("parameters") or []),
                    "response_model": response_model_name(op),
                }
            )
    # Disambiguate colliding method names
    names = [operation_method_name(o["operation_id"]) for o in ops]
    counts = Counter(names)
    used: dict[str, int] = defaultdict(int)
    for op, base in zip(ops, names, strict=True):
        if counts[base] == 1:
            op["py_name"] = base
            continue
        # Prefer tag-qualified name from operationId
        full = camel_to_snake(op["operation_id"].replace("-", "_"))
        candidate = full
        used[candidate] += 1
        if used[candidate] > 1:
            candidate = f"{full}_{used[candidate]}"
        op["py_name"] = candidate
    return ops


def generate_service(swagger: dict[str, Any], ns: str, class_name: str) -> None:
    ops = collect_operations(swagger)
    models_needed: set[str] = set()
    for op in ops:
        if op["response_model"]:
            models_needed.add(op["response_model"])
        for param in op["parameters"]:
            if param.get("in") == "body":
                ref = schema_ref_name(param.get("schema") or {})
                if ref:
                    models_needed.add(ref)

    # Only import models that datamodel-codegen actually emitted.
    available = _model_class_names(ns)
    missing = sorted(models_needed - available)
    if missing:
        print(
            f"  warning: {ns}: {len(missing)} response/body models missing from "
            f"generated module (will use Any): {missing[:5]}",
            file=sys.stderr,
        )
    models_needed &= available
    # Patch ops that referenced missing models
    for op in ops:
        if op["response_model"] and op["response_model"] not in available:
            op["response_model"] = None

    lines: list[str] = [
        f'# Generated by scripts/generate_from_openapi.py — namespace "{ns}"',
        "# Do not edit by hand.",
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "from zedcloud.services.base import BaseService",
    ]
    if models_needed:
        # import models used in signatures / response_model=
        sorted_models = sorted(models_needed)
        lines.append(f"from zedcloud._generated.models.{ns} import (")
        for name in sorted_models:
            lines.append(f"    {name},")
        lines.append(")")
    lines += ["", "", f"class {class_name}(BaseService):"]
    title = (swagger.get("info") or {}).get("title") or ns
    lines.append(f'    """Auto-generated client for {title}."""')
    lines.append("")

    if not ops:
        lines.append("    pass")
        lines.append("")
    else:
        for op in ops:
            lines.extend(render_method(op, available_models=available))
            lines.append("")

    dest = SERVICES_DIR / f"{ns}.py"
    dest.write_text("\n".join(lines).rstrip() + "\n")


def _model_class_names(ns: str) -> set[str]:
    path = MODELS_DIR / f"{ns}.py"
    if not path.exists():
        return set()
    names: set[str] = set()
    for line in path.read_text().splitlines():
        if line.startswith("class ") and "(" in line:
            names.add(line[len("class ") :].split("(", 1)[0].strip())
    return names


def render_method(
    op: dict[str, Any],
    *,
    available_models: set[str] | None = None,
) -> list[str]:
    path = op["path"]
    method = op["method"]
    py_name = op["py_name"]
    response_model = op["response_model"]
    if response_model and available_models is not None and response_model not in available_models:
        response_model = None
    path_params: list[dict[str, Any]] = []
    query_params: list[dict[str, Any]] = []
    header_params: list[dict[str, Any]] = []
    body_param: dict[str, Any] | None = None

    for param in op["parameters"]:
        where = param.get("in")
        if where == "path":
            path_params.append(param)
        elif where == "query":
            query_params.append(param)
        elif where == "header":
            header_params.append(param)
        elif where == "body":
            body_param = param

    # Signature — required params before optional (valid Python).
    required_parts: list[str] = ["self"]
    optional_parts: list[str] = []
    for param in path_params:
        pname = param_py_name(param["name"])
        ptype = python_type_for_param(param)
        required_parts.append(f"{pname}: {ptype}")
    if body_param is not None:
        btype = python_type_for_param(body_param)
        # If referenced model wasn't generated, fall back to dict.
        if available_models is not None and "|" in btype:
            model = btype.split("|", 1)[0].strip()
            if model not in available_models and model not in {"dict[str, Any]", "Any"}:
                btype = "dict[str, Any] | Any"
        if body_param.get("required", True):
            required_parts.append(f"body: {btype}")
        else:
            optional_parts.append(f"body: {btype} | None = None")
    for param in query_params + header_params:
        pname = param_py_name(param["name"])
        ptype = python_type_for_param(param)
        if param.get("required"):
            required_parts.append(f"{pname}: {ptype}")
        else:
            optional_parts.append(f"{pname}: {ptype} | None = None")
    sig_parts = required_parts + optional_parts

    ret = response_model if response_model else "Any"
    # Docstring
    summary = op["summary"] or op["operation_id"]
    doc_lines = [
        f'        """{summary}',
        "",
        f"        ``{method} {path}``",
        f"        operationId: ``{op['operation_id']}``",
        '        """',
    ]

    # Body
    body_lines: list[str] = []
    # path formatting
    fmt_path = path
    path_format_args: list[str] = []
    for param in path_params:
        swagger_name = param["name"]
        pname = param_py_name(swagger_name)
        # replace {id} style
        fmt_path = fmt_path.replace("{" + swagger_name + "}", "{" + pname + "}")
        path_format_args.append(f"{pname}={pname}")
    if path_params:
        body_lines.append(f'        path = f"{fmt_path}"')
    else:
        body_lines.append(f'        path = "{fmt_path}"')

    body_lines.append("        params: dict[str, Any] = {}")
    for param in query_params:
        sname = param["name"]
        pname = param_py_name(sname)
        body_lines.append(f"        if {pname} is not None:")
        body_lines.append(f'            params["{sname}"] = {pname}')

    body_lines.append("        headers: dict[str, str] = {}")
    for param in header_params:
        sname = param["name"]
        pname = param_py_name(sname)
        body_lines.append(f"        if {pname} is not None:")
        body_lines.append(f'            headers["{sname}"] = {pname}')

    call_args = [
        f'"{method}"',
        "path",
        "params=params or None",
        "headers=headers or None",
    ]
    if body_param is not None:
        call_args.append("json_body=body")
    if response_model:
        call_args.append(f"response_model={response_model}")
    else:
        call_args.append("response_model=None")

    body_lines.append(f"        return self._request({', '.join(call_args)})")

    # Assemble
    # Keep signature readable — if long, use multiline
    if len(", ".join(sig_parts)) > 90:
        sig = "(\n        " + ",\n        ".join(sig_parts) + f",\n    ) -> {ret}:"
    else:
        sig = f"({', '.join(sig_parts)}) -> {ret}:"

    out = [f"    def {py_name}{sig}"]
    out.extend(doc_lines)
    out.extend(body_lines)
    return out


def write_models_all() -> None:
    """Write a convenience ``models/__init__`` exporting nothing heavy."""
    namespaces = [ns for ns, _ in SERVICE_MAP.values()]
    lines = [
        '"""Generated Pydantic models per Zedcloud service.',
        "",
        "Import from a concrete module, e.g.::",
        "",
        "    from zedcloud._generated.models.apps import Apps, AppSummary",
        '"""',
        "",
        "__all__: list[str] = []",
        "",
    ]
    for ns in namespaces:
        lines.append(f"# - zedcloud._generated.models.{ns}")
    (MODELS_DIR / "__init__.py").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
