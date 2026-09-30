#!/usr/bin/env python3
"""Download the current Zedcloud OpenAPI specs into ``openapi/``.

The service list is read from the controller's Swagger UI page, so new
services show up automatically (add them to ``SERVICES`` in generate.py).

Usage::

    uv run python scripts/fetch_specs.py [--base-url https://zedcontrol.zededa.net]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIR = ROOT / "openapi"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="https://zedcontrol.zededa.net")
    args = parser.parse_args()
    docs = f"{args.base_url.rstrip('/')}/api/v1/docs/"
    with httpx.Client(timeout=60, follow_redirects=True) as http:
        page = http.get(docs)
        page.raise_for_status()
        urls = re.findall(r'url:\s*"\./(zapiservices/[^"]+\.swagger\.json)"', page.text)
        if not urls:
            raise SystemExit(f"no spec URLs found on {docs}")
        for rel in urls:
            spec = http.get(docs + rel)
            spec.raise_for_status()
            dest = OPENAPI_DIR / Path(rel).name
            data = spec.json()
            changed = not dest.exists() or json.loads(dest.read_text()) != data
            if changed:
                dest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            print(f"{'updated  ' if changed else 'unchanged'} {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
