"""Audit logging and observability."""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings, get_settings
from app.models.schemas import AuditLogEntry


class AuditLogger:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.log_path = self.settings.audit_log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[AuditLogEntry] = []

    def log(self, entry: AuditLogEntry) -> None:
        self._entries.append(entry)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def get_recent(self, limit: int = 50) -> list[AuditLogEntry]:
        if not self.log_path.exists():
            return self._entries[-limit:]

        entries: list[AuditLogEntry] = []
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(AuditLogEntry.model_validate_json(line))
                    except Exception:
                        continue
        return entries[-limit:]

    def get_stats(self) -> dict:
        recent = self.get_recent(1000)
        return {
            "total_logged": len(recent),
            "rbac_violations": sum(1 for e in recent if e.rbac_violation),
            "security_violations": sum(1 for e in recent if e.security_violation),
            "avg_response_time_ms": (
                round(sum(e.response_time_ms or 0 for e in recent) / len(recent), 2) if recent else 0
            ),
        }
