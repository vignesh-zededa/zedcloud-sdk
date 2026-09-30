"""``zedcloud`` command-line interface.

Examples::

    zedcloud profiles
    zedcloud -p acme-prod whoami
    zedcloud ops search "reboot edge node"
    zedcloud ops show EdgeNodeConfiguration_Reboot
    zedcloud -p acme-prod call nodes.query_edge_nodes -q project_name=plant-7 -q page_size=5
    zedcloud -p lab call nodes.reboot --path id=<uuid> --yes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from zedcloud.client import ZedcloudClient
from zedcloud.config import default_config_path, load_profiles
from zedcloud.errors import ApiError, ZedcloudError
from zedcloud.operations import get_operation, search_operations


def _json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


def _pairs(items: list[str] | None, flag: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"{flag} expects key=value, got {item!r}")
        # Repeated keys become lists (e.g. -q order_by=name -q order_by=title).
        if key in out:
            out[key] = [*([out[key]] if not isinstance(out[key], list) else out[key]), value]
        else:
            out[key] = value
    return out


def _client(args: argparse.Namespace) -> ZedcloudClient:
    return ZedcloudClient(profile=args.profile) if args.profile else ZedcloudClient()


def cmd_profiles(args: argparse.Namespace) -> int:
    profiles, default = load_profiles(args.config)
    if not profiles:
        print(f"no profiles in {args.config or default_config_path()}")
        return 0
    width = max(len(n) for n in profiles)
    for name, prof in sorted(profiles.items()):
        marker = "*" if name == default else " "
        writes = "writes" if prof.allow_writes else "read-only"
        detail = f"  {prof.description}" if prof.description else ""
        print(f"{marker} {name:<{width}}  {prof.base_url}  [{prof.auth_kind}, {writes}]{detail}")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    with _client(args) as zc:
        print(f"# {zc.config.label}")
        print(_json(zc.whoami()))
    return 0


def cmd_ops_search(args: argparse.Namespace) -> int:
    for op in search_operations(args.query, service=args.service, risk=args.risk, limit=args.limit):
        print(f"{op.service}.{op.method_name:<52} {op.http_method:<6} {op.path}  [{op.risk}]")
    return 0


def cmd_ops_show(args: argparse.Namespace) -> int:
    op = get_operation(args.operation)
    print(op.summary_line())
    print(f"python: client.{op.service}.{op.method_name}(...)")
    if op.description:
        print(f"\n{op.description}")
    if op.params:
        print("\nparameters:")
        for p in op.params:
            req = "required" if p.required else "optional"
            print(f"  {p.name} ({p.location}, {p.type}, {req}) {p.description}")
    if op.body_model:
        print(f"\nbody model: zedcloud.models.{op.body_model}")
    if op.response_model:
        print(f"response model: zedcloud.models.{op.response_model}")
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    op = get_operation(args.operation)
    if op.risk != "read" and not args.yes:
        print(
            f"{op.operation_id} is a {op.risk} operation ({op.http_method} {op.path}); "
            "re-run with --yes to execute",
            file=sys.stderr,
        )
        return 2
    body = None
    if args.body:
        text = Path(args.body[1:]).read_text() if args.body.startswith("@") else args.body
        body = json.loads(text)
    with _client(args) as zc:
        result = zc.call(
            op.operation_id,
            path=_pairs(args.path, "--path"),
            query=_pairs(args.query, "--query"),
            body=body,
        )
    if result is not None:
        print(_json(result) if not isinstance(result, str) else result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zedcloud", description="ZEDEDA Zedcloud API client")
    parser.add_argument(
        "-p", "--profile", help="profile name (default: ZEDCLOUD_PROFILE / file default)"
    )
    parser.add_argument("--config", help="profiles file (default: ~/.config/zedcloud/config.toml)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profiles", help="list configured tenant profiles").set_defaults(
        func=cmd_profiles
    )
    sub.add_parser("whoami", help="show the session for a profile").set_defaults(func=cmd_whoami)

    ops = sub.add_parser("ops", help="discover API operations").add_subparsers(
        dest="ops", required=True
    )
    search = ops.add_parser("search", help="search operations by keywords")
    search.add_argument("query")
    search.add_argument("--service")
    search.add_argument("--risk", choices=["read", "write", "destructive"])
    search.add_argument("--limit", type=int, default=15)
    search.set_defaults(func=cmd_ops_search)
    show = ops.add_parser("show", help="describe one operation")
    show.add_argument("operation", help="operationId or service.method_name")
    show.set_defaults(func=cmd_ops_show)

    call = sub.add_parser("call", help="invoke an operation")
    call.add_argument("operation", help="operationId or service.method_name")
    call.add_argument("--path", action="append", metavar="KEY=VALUE", help="path parameter")
    call.add_argument("-q", "--query", action="append", metavar="KEY=VALUE", help="query parameter")
    call.add_argument("--body", help="JSON body, or @file.json")
    call.add_argument("--yes", action="store_true", help="allow write/destructive operations")
    call.set_defaults(func=cmd_call)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (ZedcloudError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
