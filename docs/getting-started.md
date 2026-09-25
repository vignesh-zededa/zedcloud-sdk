# Getting started

1. Install [uv](https://docs.astral.sh/uv/).
2. `uv sync --all-packages --group dev`
3. `make generate` (if `_generated` is missing or specs changed)
4. Copy `.env.example` → export `ZEDCLOUD_BASE_URL` and `ZEDCLOUD_TOKEN`
5. Try:

```python
from zedcloud import ZedcloudClient

with ZedcloudClient.from_env() as c:
    print(c.apps.query_edge_application_bundles(next_page_size=5, summary=True))
```

See the root [README](../README.md) for MCP config and automation markers.
