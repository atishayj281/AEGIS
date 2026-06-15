"""CSV dataset retriever for operational data."""

import csv
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings
from app.models.domain import DataSource


@dataclass
class CSVResult:
    content: str
    source_name: str
    data_source: DataSource
    score: float
    row_count: int


class CSVRetriever:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.csv_dir = self.settings.data_dir / "csv"

    def retrieve(self, query: str, allowed_sources: list[DataSource]) -> list[CSVResult]:
        if DataSource.OPERATIONAL_DATASETS not in allowed_sources and DataSource.SYSTEM_METRICS not in allowed_sources:
            return []

        query_lower = query.lower()
        if not any(k in query_lower for k in ["cpu", "server", "metric", "threshold", "performance", "operational"]):
            return []

        results: list[CSVResult] = []
        metrics_file = self.csv_dir / "server_metrics.csv"
        if not metrics_file.exists():
            return results

        with open(metrics_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if "threshold" in query_lower or "exceeded" in query_lower or "critical" in query_lower:
            filtered = [r for r in rows if r.get("status") == "critical"]
        elif "last week" in query_lower or "week" in query_lower:
            filtered = rows
        else:
            filtered = [r for r in rows if float(r.get("cpu_percent", 0)) >= 85]

        if not filtered:
            filtered = rows[:5]

        lines = [
            f"{r['date']} | {r['server_id']} | CPU: {r['cpu_percent']}% | "
            f"Memory: {r['memory_percent']}% | Status: {r['status']}"
            for r in filtered
        ]

        results.append(
            CSVResult(
                content="Server Metrics:\n" + "\n".join(lines),
                source_name="server_metrics.csv",
                data_source=DataSource.SYSTEM_METRICS,
                score=0.88,
                row_count=len(filtered),
            )
        )

        return results
