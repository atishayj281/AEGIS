"""JSON log retriever for audit and monitoring data."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings, get_settings
from app.models.domain import DataSource


@dataclass
class JSONResult:
    content: str
    source_name: str
    data_source: DataSource
    score: float
    row_count: int


class JSONRetriever:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.json_dir = self.settings.data_dir / "json"

    def retrieve(self, query: str, allowed_sources: list[DataSource]) -> list[JSONResult]:
        if DataSource.AUDIT_LOGS not in allowed_sources and DataSource.MONITORING_LOGS not in allowed_sources:
            return []

        query_lower = query.lower()
        if not any(
            k in query_lower
            for k in ["login", "audit", "failed", "security", "incident", "access", "attempt"]
        ):
            return []

        log_file = self.json_dir / "audit_logs.json"
        if not log_file.exists():
            return []

        with open(log_file, encoding="utf-8") as f:
            logs = json.load(f)

        if "failed login" in query_lower or "login attempt" in query_lower:
            filtered = [log for log in logs if log.get("event_type") == "login_failed"]
        elif "last 24 hours" in query_lower or "24 hour" in query_lower:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            filtered = [
                log
                for log in logs
                if log.get("event_type") == "login_failed"
                and self._parse_ts(log["timestamp"]) >= cutoff
            ]
        else:
            filtered = [log for log in logs if log.get("event_type") == "login_failed"]

        if not filtered:
            filtered = logs[:5]

        lines = [
            f"{log['timestamp']} | {log['event_type']} | user={log['username']} | "
            f"ip={log['source_ip']} | reason={log.get('reason', 'N/A')} | severity={log['severity']}"
            for log in filtered
        ]

        return [
            JSONResult(
                content=f"Audit Log Entries ({len(filtered)} records):\n" + "\n".join(lines),
                source_name="audit_logs.json",
                data_source=DataSource.AUDIT_LOGS,
                score=0.92,
                row_count=len(filtered),
            )
        ]

    def _parse_ts(self, ts: str) -> datetime:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
