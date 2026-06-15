"""SQL database retriever for structured enterprise data."""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings
from app.models.domain import DataSource


@dataclass
class SQLResult:
    content: str
    source_name: str
    data_source: DataSource
    score: float
    row_count: int


class SQLRetriever:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY,
        vendor_name TEXT NOT NULL,
        amount REAL NOT NULL,
        status TEXT NOT NULL,
        due_date TEXT NOT NULL,
        invoice_date TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS salary_records (
        id INTEGER PRIMARY KEY,
        employee_name TEXT NOT NULL,
        department TEXT NOT NULL,
        annual_salary REAL NOT NULL,
        role_level TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS budget_reports (
        id INTEGER PRIMARY KEY,
        department TEXT NOT NULL,
        fiscal_year INTEGER NOT NULL,
        allocated REAL NOT NULL,
        spent REAL NOT NULL,
        remaining REAL NOT NULL
    );
    """

    SEED_INVOICES = [
        ("Vendor ABC", 45000.00, "pending", "2026-02-15", "2026-01-10"),
        ("Vendor ABC", 12500.00, "paid", "2026-01-05", "2025-12-20"),
        ("CloudHost Inc", 8900.00, "pending", "2026-02-01", "2026-01-12"),
        ("SecureNet Ltd", 22000.00, "approved", "2026-02-20", "2026-01-08"),
        ("Office Supplies Co", 3400.00, "paid", "2026-01-15", "2025-12-28"),
    ]

    SEED_SALARIES = [
        ("John Executive", "Executive", 450000.00, "C-Level"),
        ("Jane Director", "Engineering", 220000.00, "Director"),
        ("Bob Analyst", "Finance", 95000.00, "Senior"),
        ("Alice Engineer", "Operations", 110000.00, "Senior"),
    ]

    SEED_BUDGETS = [
        ("Engineering", 2026, 2500000.00, 1800000.00, 700000.00),
        ("Finance", 2026, 800000.00, 450000.00, 350000.00),
        ("Operations", 2026, 1200000.00, 980000.00, 220000.00),
        ("Compliance", 2026, 500000.00, 320000.00, 180000.00),
    ]

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.db_path = self.settings.sqlite_path
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(self.SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO invoices (vendor_name, amount, status, due_date, invoice_date) VALUES (?, ?, ?, ?, ?)",
                self.SEED_INVOICES,
            )
            conn.executemany(
                "INSERT INTO salary_records (employee_name, department, annual_salary, role_level) VALUES (?, ?, ?, ?)",
                self.SEED_SALARIES,
            )
            conn.executemany(
                "INSERT INTO budget_reports (department, fiscal_year, allocated, spent, remaining) VALUES (?, ?, ?, ?, ?)",
                self.SEED_BUDGETS,
            )
            conn.commit()
        conn.close()

    def retrieve(self, query: str, allowed_sources: list[DataSource]) -> list[SQLResult]:
        results: list[SQLResult] = []
        query_lower = query.lower()

        if DataSource.INVOICE_RECORDS in allowed_sources:
            invoice_result = self._query_invoices(query_lower)
            if invoice_result:
                results.append(invoice_result)

        if DataSource.SALARY_RECORDS in allowed_sources:
            salary_result = self._query_salaries(query_lower)
            if salary_result:
                results.append(salary_result)

        if DataSource.BUDGET_REPORTS in allowed_sources:
            budget_result = self._query_budgets(query_lower)
            if budget_result:
                results.append(budget_result)

        if DataSource.FINANCIAL_DATABASE in allowed_sources:
            financial = self._query_financial_summary(query_lower)
            if financial:
                results.append(financial)

        return results

    def _query_invoices(self, query: str) -> SQLResult | None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        vendor_match = re.search(r"vendor\s+(\w+)", query, re.IGNORECASE)
        if vendor_match:
            vendor = vendor_match.group(1)
            if "pending" in query:
                rows = conn.execute(
                    "SELECT * FROM invoices WHERE LOWER(vendor_name) LIKE ? AND status = 'pending' ORDER BY due_date",
                    (f"%{vendor.lower()}%",),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM invoices WHERE LOWER(vendor_name) LIKE ? ORDER BY due_date",
                    (f"%{vendor.lower()}%",),
                ).fetchall()
        elif any(k in query for k in ["invoice", "pending", "vendor", "payment"]):
            status = "pending" if "pending" in query else None
            if status:
                rows = conn.execute(
                    "SELECT * FROM invoices WHERE status = ? ORDER BY due_date", (status,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM invoices ORDER BY due_date LIMIT 10").fetchall()
        else:
            conn.close()
            return None

        conn.close()
        if not rows:
            return None

        lines = []
        for row in rows:
            lines.append(
                f"Invoice #{row['id']}: {row['vendor_name']} - ${row['amount']:,.2f} "
                f"({row['status']}) due {row['due_date']}"
            )

        return SQLResult(
            content="\n".join(lines),
            source_name="invoices.db",
            data_source=DataSource.INVOICE_RECORDS,
            score=0.9,
            row_count=len(rows),
        )

    def _query_salaries(self, query: str) -> SQLResult | None:
        if not any(k in query for k in ["salary", "compensation", "payroll", "executive pay"]):
            return None

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM salary_records ORDER BY annual_salary DESC").fetchall()
        conn.close()

        lines = [
            f"{row['employee_name']} ({row['department']}, {row['role_level']}): "
            f"${row['annual_salary']:,.2f}/year"
            for row in rows
        ]

        return SQLResult(
            content="\n".join(lines),
            source_name="salary_records.db",
            data_source=DataSource.SALARY_RECORDS,
            score=0.95,
            row_count=len(rows),
        )

    def _query_budgets(self, query: str) -> SQLResult | None:
        if not any(k in query for k in ["budget", "allocated", "fiscal", "spending"]):
            return None

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM budget_reports WHERE fiscal_year = 2026 ORDER BY department"
        ).fetchall()
        conn.close()

        lines = [
            f"{row['department']}: Allocated ${row['allocated']:,.0f}, "
            f"Spent ${row['spent']:,.0f}, Remaining ${row['remaining']:,.0f}"
            for row in rows
        ]

        return SQLResult(
            content="\n".join(lines),
            source_name="budget_reports.db",
            data_source=DataSource.BUDGET_REPORTS,
            score=0.85,
            row_count=len(rows),
        )

    def _query_financial_summary(self, query: str) -> SQLResult | None:
        if not any(k in query for k in ["financial", "revenue", "expense", "summary"]):
            return None

        conn = sqlite3.connect(self.db_path)
        total_pending = conn.execute(
            "SELECT SUM(amount) FROM invoices WHERE status = 'pending'"
        ).fetchone()[0]
        total_paid = conn.execute(
            "SELECT SUM(amount) FROM invoices WHERE status = 'paid'"
        ).fetchone()[0]
        conn.close()

        content = (
            f"Financial Summary:\n"
            f"- Total pending invoices: ${total_pending:,.2f}\n"
            f"- Total paid invoices: ${total_paid:,.2f}"
        )

        return SQLResult(
            content=content,
            source_name="financial_database.db",
            data_source=DataSource.FINANCIAL_DATABASE,
            score=0.8,
            row_count=1,
        )
