# Zedcloud Python SDK

Typed Python client, pytest automation helpers, and MCP server for
[ZEDEDA Zedcloud](https://zededa.com/) control-plane APIs.

OpenAPI specs are committed under [`openapi/`](openapi/) (mirrors of the
Swagger UI at `https://zedcontrol.zededa.net/api/v1/docs/`).

## Packages

| Package | Description |
|---------|-------------|
| [`zedcloud`](packages/zedcloud) | Typed sync SDK (`httpx` + Pydantic v2) |
| [`zedcloud-automation`](packages/zedcloud-automation) | Pytest fixtures, markers, resource cleanup |
| [`zedcloud-mcp`](packages/zedcloud-mcp) | MCP server (stdio) exposing high-value tools |

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Install

```bash
# clone
git clone https://github.com/vignesh-zededa/zedcloud-sdk.git
cd zedcloud-sdk

# workspace (SDK + automation + MCP + dev tools)
uv sync --all-packages --group dev

# regenerate models/services from openapi/*.swagger.json
uv run python scripts/generate_from_openapi.py
# or: make generate
```

Editable install of just the SDK:

```bash
uv pip install -e packages/zedcloud
# or: pip install -e packages/zedcloud
```

## Auth

Copy [`.env.example`](.env.example) and export:

```bash
export ZEDCLOUD_BASE_URL=https://zedcontrol.zededa.net
export ZEDCLOUD_TOKEN=YOUR_SESSION_TOKEN
# optional — Kubernetes/ZKS also sends X-API-KEY (defaults to the bearer token)
# export ZEDCLOUD_API_KEY=…
```

Most services use `Authorization: Bearer <token>`. The Kubernetes / ZKS service
uses `ApiKeyAuth` (`X-API-KEY`); the client sends both headers for that namespace.

## SDK quickstart

```python
from zedcloud import ZedcloudClient
from zedcloud.pagination import collect_all

with ZedcloudClient.from_env() as client:
    apps = client.apps.query_edge_application_bundles(next_page_size=25, summary=True)
    for app in apps.list_ or []:  # OpenAPI field ``list`` is exposed as ``list_``
        print(app.id, app.name)

    nodes = collect_all(client.nodes.query_edge_nodes, page_size=50, summary=True)
    print(f"{len(nodes)} nodes")

    # Kubernetes / ZKS (ApiKeyAuth)
    clusters = client.k8s.list_zks_instances()
```

Service namespaces map to OpenAPI specs:

`apps`, `nodes`, `networks`, `iam`, `k8s`, `storage`, `jobs`, `orchestration`,
`diag`, `app_profiles`, `node_clusters`.

Methods are generated from swagger `operationId` values (snake_case). Each
method docstring includes the HTTP verb/path.

## Codegen

```bash
make generate
# equivalent:
uv run python scripts/generate_from_openapi.py
```

Pipeline:

1. Convert each Swagger 2.0 `definitions` map → OpenAPI 3 `components/schemas`
2. Run `datamodel-code-generator` → Pydantic v2 models
3. Emit typed service wrappers under `zedcloud._generated.services`

Do not hand-edit `_generated/`; change swagger or the generator script instead.

## Automation

```bash
# mocked / offline unit tests
uv run pytest -q -m "not needs_cloud"

# live read-only smoke (requires credentials)
uv run pytest -q -m "smoke and needs_cloud"
```

Fixtures (`zedcloud_client`, `resource_tracker`) are registered via the
`zedcloud-automation` pytest plugin.

## MCP server

```bash
uv run zedcloud-mcp
```

Focused tools (not the full ~470 endpoints): nodes, apps, networks, ZKS/k8s, jobs.

### Cursor

Add to MCP settings (`.cursor/mcp.json` or Cursor Settings → MCP):

```json
{
  "mcpServers": {
    "zedcloud": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/zedcloud-sdk", "zedcloud-mcp"],
      "env": {
        "ZEDCLOUD_BASE_URL": "https://zedcontrol.zededa.net",
        "ZEDCLOUD_TOKEN": "YOUR_SESSION_TOKEN"
      }
    }
  }
}
```

### Claude Desktop

```json
{
  "mcpServers": {
    "zedcloud": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/zedcloud-sdk", "zedcloud-mcp"],
      "env": {
        "ZEDCLOUD_BASE_URL": "https://zedcontrol.zededa.net",
        "ZEDCLOUD_TOKEN": "YOUR_SESSION_TOKEN"
      }
    }
  }
}
```

List tools without starting a session:

```bash
make mcp-list
```

## Development

```bash
make sync      # uv sync --all-packages --group dev
make generate  # regenerate from openapi/
make test      # unit tests (skips needs_cloud)
make lint      # ruff
```

CI (`.github/workflows/ci.yml`) runs lint, verifies codegen is clean, and executes
mocked unit tests on Python 3.10 and 3.12.

## License

MIT — see [LICENSE](LICENSE).
