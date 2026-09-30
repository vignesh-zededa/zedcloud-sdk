# zedcloud

Typed Python client (sync and async) for the ZEDEDA Zedcloud API.

```python
from zedcloud import ZedcloudClient

with ZedcloudClient.from_profile("acme-prod") as zc:
    node = zc.nodes.lookup_edge_node("gw-17")
    print(node.name, zc.nodes.get_edge_node_status(node.id).run_state)
```

Install `zedcloud[keyring]` to read credentials from the OS keychain. See the
[repository README](../../README.md) and [getting started](../../docs/getting-started.md).
