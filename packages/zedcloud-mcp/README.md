# zedcloud-mcp

An MCP server that lets a chat assistant work with one or more Zedcloud
tenants, using the profiles from `~/.config/zedcloud/config.toml`.

```bash
uv run zedcloud-mcp                        # stdio
uv run zedcloud-mcp --read-only            # refuse every write
uv run zedcloud-mcp --require-human-approval
uv run zedcloud-mcp --list-tools
```

## Tools

| Tool | Purpose |
|---|---|
| `list_tenants`, `use_tenant`, `whoami` | see and switch tenants; confirm the logged-in user/enterprise |
| `fleet_health` | counts by run state, plus nodes and app instances that are not online |
| `list_edge_nodes`, `get_edge_node` | edge nodes (by name or ID), with live status |
| `list_app_instances`, `get_app_instance` | app instances, with live status |
| `list_projects`, `recent_events`, `get_job` | projects, per-object events, background jobs |
| `search_operations`, `describe_operation`, `describe_model` | discover any of the 470 API operations |
| `call_read_operation` | run any read-only operation |
| `plan_write_operation` → `execute_write_operation` | preview, then run, a change |

Every tool takes an optional `tenant`, and every result names the tenant it came from.

## Safety model

- **Read-only by default.** Writes need `allow_writes = true` on the profile, and
  `--read-only` overrides every profile.
- **Preview before change.** `plan_write_operation` changes nothing. It fetches
  the target, merges partial update bodies onto the current object (Zedcloud
  updates replace the whole object), shows a field-by-field diff, and flags
  destructive operations (delete, reboot, offboard, purge, upgrade, …).
- **Exactly what was previewed.** The plan is stored server-side under a random,
  single-use, 10-minute token; `execute_write_operation` takes only the token.
- **Human in the loop.** Clients mark `execute_write_operation` as destructive
  and ask before running it. If the client supports MCP elicitation, the server
  also asks you directly. `--require-human-approval` refuses writes when it can't.
- **Audit log.** `~/.local/state/zedcloud/mcp-audit.jsonl` (or `--audit-log`) records
  every planned, executed, declined, and failed change, with secrets redacted.
- **Context hygiene.** Results drop empty fields, truncate long lists and strings,
  and redact secret-looking fields. The server tells the assistant to treat data
  returned by Zedcloud as untrusted.

## Client configuration

```json
{
  "mcpServers": {
    "zedcloud": {
      "command": "uv",
      "args": ["--directory", "/path/to/zedcloud-sdk", "run", "zedcloud-mcp"],
      "env": { "ACME_ZEDCLOUD_TOKEN": "…" }
    }
  }
}
```

With Claude Code: `claude mcp add zedcloud -- uv --directory /path/to/zedcloud-sdk run zedcloud-mcp`.
