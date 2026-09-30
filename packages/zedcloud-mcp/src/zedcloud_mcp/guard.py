"""Two-phase execution and auditing for state-changing operations.

``plan`` validates a request and stores it server-side under a random,
single-use token that expires. ``take`` hands back exactly that stored
request, so what executes is what was previewed; the model cannot alter
parameters between preview and execution. Every plan, execution, and failure
is appended to a JSONL audit log with secret-looking fields redacted.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_KEY = re.compile(
    r"pass(word)?|secret|token|api[-_]?key|credential|private[-_]?key|cert", re.I
)
REDACTED = "***"


def default_audit_path() -> Path:
    if env := os.environ.get("ZEDCLOUD_MCP_AUDIT_LOG"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "zedcloud" / "mcp-audit.jsonl"


def redact(value: Any) -> Any:
    """Replace values under secret-looking keys, recursively."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if SECRET_KEY.search(str(k)) and v not in (None, "") else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


@dataclass
class WritePlan:
    token: str
    tenant: str
    operation_id: str
    risk: str
    http_method: str
    path_template: str
    rendered_path: str
    path: dict[str, Any]
    query: dict[str, Any]
    body: Any
    summary: str
    expires_at: float
    preview: dict[str, Any] = field(default_factory=dict)


class PlanError(Exception):
    """A confirmation token is unknown, used, or expired."""


class WriteGuard:
    def __init__(self, *, ttl: float = 600.0, audit_path: Path | None = None) -> None:
        self.ttl = ttl
        self.audit_path = audit_path or default_audit_path()
        self._plans: dict[str, WritePlan] = {}

    def create(self, **fields: Any) -> WritePlan:
        self._expire()
        plan = WritePlan(
            token=secrets.token_urlsafe(18), expires_at=time.time() + self.ttl, **fields
        )
        self._plans[plan.token] = plan
        self.audit("planned", plan)
        return plan

    def take(self, token: str) -> WritePlan:
        self._expire()
        plan = self._plans.pop(token, None)
        if plan is None:
            raise PlanError(
                "unknown, already used, or expired confirmation token; "
                "call plan_write_operation again"
            )
        return plan

    def discard(self, token: str) -> bool:
        return self._plans.pop(token, None) is not None

    def _expire(self) -> None:
        now = time.time()
        for token in [t for t, p in self._plans.items() if p.expires_at < now]:
            del self._plans[token]

    def audit(self, event: str, plan: WritePlan, **extra: Any) -> None:
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            "tenant": plan.tenant,
            "operation_id": plan.operation_id,
            "risk": plan.risk,
            "request": f"{plan.http_method} {plan.rendered_path}",
            "query": redact(plan.query),
            "body": redact(plan.body),
            **extra,
        }
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
            os.chmod(self.audit_path, 0o600)
        except OSError:
            pass  # auditing must never block the operation itself
