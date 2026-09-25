# zedcloud-sdk

Python SDK, pytest automation framework, and MCP server for the
[ZEDEDA Zedcloud API](https://zedcontrol.zededa.net/api/v1/docs/).

| Package | What it is |
|---|---|
| [`zedcloud`](packages/zedcloud) | Typed sync + async client for all 470 operations across the 11 Zedcloud services |
| [`zedcloud-automation`](packages/zedcloud-automation) | Pytest plugin: tenant fixtures, resource cleanup, write guards |
| [`zedcloud-mcp`](packages/zedcloud-mcp) | MCP server so a chat assistant can query and (safely) change a chosen tenant |

## Quick start

```bash
uv sync --all-packages --group dev
```

```python
from zedcloud import ZedcloudClient

with ZedcloudClient(base_url="https://zedcontrol.zededa.net", token="…") as zc:
    for node in zc.nodes.iter_edge_node_status(project_name="plant-7"):
        print(node.name, node.run_state)

    gw = zc.nodes.lookup_edge_node("gw-17")          # name or ID
    zc.nodes.reboot(gw.id)
    zc.nodes.wait_for_edge_node(gw.id)               # until RUN_STATE_ONLINE
```

Async works the same way:

```python
from zedcloud import AsyncZedcloudClient

async with AsyncZedcloudClient.from_profile("acme-prod") as zc:
    async for app in zc.apps.iter_edge_application_instance_status(run_state="ERROR"):
        print(app.name, app.device_name)
```

## Tenants and credentials

Each tenant is a *profile*: a controller URL plus one user's credentials
(a session/API token, or username + password). Profiles live in
`~/.config/zedcloud/config.toml` (override with `ZEDCLOUD_CONFIG`):

```toml
default = "acme-prod"

[profiles.acme-prod]
base_url = "https://zedcontrol.zededa.net"
token_env = "ACME_ZEDCLOUD_TOKEN"      # or token = "…", token_command = [...], token_keyring = true
description = "Acme production"

[profiles.lab]
base_url = "https://zedcontrol.zededa.net"
username = "me@example.com"
password_command = ["security", "find-generic-password", "-s", "zedcloud-lab", "-w"]
enterprise = "lab-enterprise"          # which enterprise to log into
allow_writes = true                    # lets the MCP server / integration tests change this tenant
```

```python
ZedcloudClient.from_profile("lab")     # or ZEDCLOUD_PROFILE=lab, or the file's default
```

Secrets can come from the file, an environment variable (`*_env`), a command
such as a password-manager CLI (`*_command`), or the OS keychain
(`*_keyring`, needs `zedcloud[keyring]`). Without a profile, `ZEDCLOUD_BASE_URL`
plus `ZEDCLOUD_TOKEN` or `ZEDCLOUD_USERNAME`/`ZEDCLOUD_PASSWORD` are used.
Password sessions log in on first use and log in again when the session expires.

```bash
zedcloud profiles                      # list tenants
zedcloud -p lab whoami                 # confirm which user/enterprise a profile reaches
zedcloud ops search "app instance logs"
zedcloud -p lab call nodes.query_edge_nodes -q project_name=plant-7
```

## SDK highlights

- **Every operation, typed.** One pydantic model per API definition (989),
  including typed request bodies for updates. Optional arguments are keyword-only.
- **Tolerant of API drift.** Unknown fields are kept and round-trip through
  GET → modify → PUT; enum values added server-side are accepted
  (`value.is_known` tells you); fields the spec calls required may be absent.
- **Safe retries.** Connection failures and 429s retry for any method; 5xx
  retries only for reads, so a write is never applied twice.
- **Helpers.** `iter_*` for all 56 paginated lists, `lookup_*` (name or ID)
  for 45 resource types, `wait_for_edge_node` / `wait_for_app_instance` /
  `wait_for_job`, `client.call(operation_id, …)` for registry-driven access.
- **Useful errors.** `ConflictError`, `NotFoundError`, `PermissionDeniedError`, …
  carry the Zedcloud error code, details, and the `X-Request-Id` to quote to support.

See [docs/getting-started.md](docs/getting-started.md) and
[docs/architecture.md](docs/architecture.md).

## MCP server

```bash
uv run zedcloud-mcp                    # stdio; reads the same profiles file
```

Claude Code / Claude Desktop configuration:

```json
{
  "mcpServers": {
    "zedcloud": {
      "command": "uv",
      "args": ["--directory", "/path/to/zedcloud-sdk", "run", "zedcloud-mcp"]
    }
  }
}
```

Ask things like *"which edge nodes in plant-7 are offline on acme-prod?"* or
*"on lab, rename gw-17's title to Dock 3"*. Tenants are read-only unless the
profile sets `allow_writes = true`; every change is previewed, approved by you,
executed exactly as previewed, and audit-logged. Details in
[packages/zedcloud-mcp](packages/zedcloud-mcp/README.md).

## Development

```bash
make test             # unit tests (no tenant needed)
make lint
make specs            # refresh openapi/ from the live controller and regenerate
make generate         # regenerate after editing scripts/generate.py
uv run pytest -m smoke --zedcloud-profile acme-prod   # read-only checks against a real tenant
```

Generated code lives in `packages/zedcloud/src/zedcloud/_generated/` and is
checked in; CI fails if it is out of date with `openapi/`.
