# Architecture

```
openapi/*.swagger.json            11 Swagger 2.0 specs, refreshed by scripts/fetch_specs.py
        │
        ▼
scripts/generate.py               merges definitions, hoists inline bodies, names methods
        │
        ├─► _generated/models.py          989 tolerant pydantic models (shared by all services)
        ├─► _generated/services/<ns>.py   sync + async class per service
        └─► _generated/operations.json    registry: params, models, risk per operation
                │
                ▼
zedcloud (runtime)
  config.py      profiles, credentials, secret sources
  auth.py        httpx.Auth: bearer token, login + re-login, X-API-KEY for k8s
  _transport.py  retries, path/query/body encoding, error mapping, logging
  _service.py    request dispatch, pagination, name-or-ID lookup
  services/      hand-written extensions (waiters, aliases) over generated classes
  operations.py  registry search, prepare_call validation
  client.py      ZedcloudClient / AsyncZedcloudClient
        │
   ┌────┴─────────────────┐
   ▼                      ▼
zedcloud-automation     zedcloud-mcp
pytest plugin           tenants.py · guard.py · shaping.py · server.py
```

## Why the generator is custom

The specs are gRPC-gateway output and have quirks that generic generators
handle poorly:

| Quirk | Handling |
|---|---|
| ~190 definitions repeated verbatim in several specs | merged into one module; a conflicting duplicate fails generation |
| update bodies declared inline (`body: *` minus path params) | hoisted into named `<Method>Body` models |
| `required` lists that responses do not honour | every field optional; the requirement is documented in the model docstring |
| enums that grow server-side | `OpenEnum`: unknown values become pseudo-members |
| numbered/copy-pasted operationIds (`…BaseOS2`, `HardwareModel_DeleteEdgeNode`) | `METHOD_OVERRIDES`; any remaining collision fails generation |
| `next.totalPages` (a response field) listed as a request parameter | dropped |
| multipart `formData` uploads, base64 `format: byte` bodies | `files=` and base64 encoding |
| the Kubernetes proxy `{path}` spans several segments | slashes kept, `.`/`..` segments rejected |

## Auth

| Scheme | Header | Services |
|---|---|---|
| BearerToken | `Authorization: Bearer <token>` | all |
| ApiKeyAuth | `X-API-KEY` (explicit key, or the session token) | Kubernetes |

`PasswordCredentials` log in with `POST /v1/login` (`usernameAtRealm`, or
`username` + `realm`; optional `enterpriseName`) on first use and once more on
a 401, then retry the request.

## Retries

| Failure | Retried for |
|---|---|
| connection refused / connect timeout | every method (the server never saw it) |
| 429 | every method, honouring `Retry-After` |
| 500/502/503/504 | GET/HEAD/OPTIONS only |
| read timeout, other transport errors | never (a write may have been applied) |

Backoff is exponential with jitter, capped at 30 s. All attempts of one call
share an `X-Request-Id`.

## MCP write safety

1. `plan_write_operation` validates arguments, checks `allow_writes`, fetches
   the target object, merges partial update bodies onto it, computes a
   field-level diff, and stores the exact request under a random single-use
   token (10-minute expiry).
2. The assistant shows the preview; the user approves.
3. `execute_write_operation(token)` runs the stored request, not new
   arguments. If the MCP client supports elicitation, the server also asks the
   user directly (`--require-human-approval` makes that mandatory).
4. Planned, executed, declined, and failed events go to a JSONL audit log with
   secret-looking fields redacted.
