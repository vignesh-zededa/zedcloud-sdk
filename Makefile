.PHONY: generate install test lint mcp-list sync

UV ?= uv

sync:
	$(UV) sync --all-packages --group dev

generate:
	$(UV) run python scripts/generate_from_openapi.py

install: sync generate

test:
	$(UV) run pytest -q -m "not needs_cloud"

lint:
	$(UV) run ruff check packages scripts
	$(UV) run ruff format --check packages scripts

format:
	$(UV) run ruff format packages scripts
	$(UV) run ruff check --fix packages scripts

mcp-list:
	$(UV) run python -c "from zedcloud_mcp.server import list_tool_names; print('\n'.join(list_tool_names()))"
