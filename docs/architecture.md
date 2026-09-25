# Architecture

```
openapi/*.swagger.json          # committed Swagger 2.0 specs (11 services)
        │
        ▼
scripts/generate_from_openapi.py
        │
        ├─► zedcloud._generated.models.*     # Pydantic v2 models
        └─► zedcloud._generated.services.*   # typed method wrappers
                │
                ▼
        ZedcloudClient
          ├── apps / nodes / networks / …
          └── k8s (ApiKeyAuth transport)
                │
        ┌───────┴────────┐
        ▼                ▼
zedcloud-automation   zedcloud-mcp
(pytest fixtures)     (stdio MCP tools)
```

## Auth

| Mechanism | Header | Used by |
|-----------|--------|---------|
| BearerToken | `Authorization: Bearer <token>` | All services except Kubernetes |
| ApiKeyAuth | `X-API-KEY: <key>` | `zedge_kubernetes_service` |

`ZedcloudClient` keeps two transports sharing one `httpx.Client`. The k8s
namespace sends both headers (API key defaults to the bearer token).

## Pagination

List endpoints commonly accept `next.pageToken`, `next.pageNum`,
`next.pageSize`, `next.totalPages` and return a `next` Cursor plus a `list`
array. Use `zedcloud.pagination.iter_pages` / `collect_all` with any generated
query method.
