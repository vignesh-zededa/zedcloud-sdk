# Getting started

## 1. Install

```bash
git clone https://github.com/vignesh-zededa/zedcloud-sdk && cd zedcloud-sdk
uv sync --all-packages --group dev
```

## 2. Configure a tenant

Create `~/.config/zedcloud/config.toml` and restrict it with `chmod 600`:

```toml
default = "my-tenant"

[profiles.my-tenant]
base_url = "https://zedcontrol.zededa.net"
token_env = "ZEDCLOUD_TOKEN"     # export ZEDCLOUD_TOKEN=… (a session or API token)
```

For username/password instead:

```toml
[profiles.my-tenant]
base_url = "https://zedcontrol.zededa.net"
username = "me@example.com"
password_env = "ZEDCLOUD_PASSWORD"
enterprise = "my-enterprise"     # optional: which enterprise to log into
```

Check it:

```bash
uv run zedcloud profiles
uv run zedcloud whoami
```

## 3. Use the SDK

```python
from zedcloud import ZedcloudClient, ConflictError
from zedcloud.models import UpdateEdgeNodeBody

zc = ZedcloudClient.from_profile()                 # default profile

# Lists: iter_* pages lazily; filters are keyword arguments.
offline = [n.name for n in zc.nodes.iter_edge_node_status(run_state="OFFLINE")]

# Single objects: lookup_* accepts a name or an ID.
node = zc.nodes.lookup_edge_node("gw-17")

# Updates: Zedcloud replaces the whole object, so start from the current one.
body = UpdateEdgeNodeBody.model_validate(node.to_api())
body.title = "Dock 3"
zc.nodes.update_edge_node(node.id, body)

# Actions and waiting.
zc.nodes.reboot(node.id)
zc.nodes.wait_for_edge_node(node.id, timeout=900)

# Errors carry Zedcloud's code and the request id.
try:
    zc.nodes.create_resource_group({"name": "plant-7", "title": "Plant 7", "type": "TAG_TYPE_PROJECT"})
except ConflictError as err:
    print(err.error_code, err.message, err.request_id)
```

Anything not covered by a helper is reachable by operation ID:

```python
from zedcloud.operations import search_operations

for op in search_operations("app instance logs", limit=3):
    print(op.summary_line())
zc.call("apps.get_edge_application_instance_logs_v2", path={"id": "…"})
```

Enable debug logging with `logging.getLogger("zedcloud").setLevel("DEBUG")`;
tokens and passwords are never logged.

## 4. Write tests

```python
import pytest

@pytest.mark.smoke
def test_projects_listable(zedcloud_client):
    assert list(zedcloud_client.nodes.iter_resource_groups(max_items=1)) is not None

@pytest.mark.integration          # skipped unless the profile sets allow_writes = true
def test_project_lifecycle(zedcloud_client, resource_tracker):
    ...
```

```bash
uv run pytest -m smoke --zedcloud-profile my-tenant
```

## 5. Chat with a tenant

See [packages/zedcloud-mcp](../packages/zedcloud-mcp/README.md).
