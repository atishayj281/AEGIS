"""Role-Based Access Control engine."""

from app.models.domain import DataSource, UserRole

ROLE_PERMISSIONS: dict[UserRole, set[DataSource]] = {
    UserRole.ADMIN: {
        DataSource.COMPLIANCE_RECORDS,
        DataSource.AUDIT_LOGS,
        DataSource.FINANCIAL_DATABASE,
        DataSource.INVOICE_RECORDS,
        DataSource.BUDGET_REPORTS,
        DataSource.MONITORING_LOGS,
        DataSource.INFRASTRUCTURE_REPORTS,
        DataSource.SYSTEM_METRICS,
        DataSource.OPERATIONAL_DATASETS,
        DataSource.PDF_DOCUMENTS,
        DataSource.PUBLIC_POLICIES,
        DataSource.INTERNAL_DOCUMENTATION,
        DataSource.SALARY_RECORDS,
    },
    UserRole.COMPLIANCE_OFFICER: {
        DataSource.COMPLIANCE_RECORDS,
        DataSource.AUDIT_LOGS,
        DataSource.PDF_DOCUMENTS,
        DataSource.PUBLIC_POLICIES,
    },
    UserRole.FINANCE_ANALYST: {
        DataSource.FINANCIAL_DATABASE,
        DataSource.INVOICE_RECORDS,
        DataSource.BUDGET_REPORTS,
        DataSource.PUBLIC_POLICIES,
    },
    UserRole.OPERATIONS_ENGINEER: {
        DataSource.MONITORING_LOGS,
        DataSource.INFRASTRUCTURE_REPORTS,
        DataSource.SYSTEM_METRICS,
        DataSource.OPERATIONAL_DATASETS,
        DataSource.AUDIT_LOGS,
        DataSource.PUBLIC_POLICIES,
    },
    UserRole.EMPLOYEE: {
        DataSource.PUBLIC_POLICIES,
        DataSource.INTERNAL_DOCUMENTATION,
    },
}

INTENT_DEFAULT_SOURCES: dict[str, list[DataSource]] = {
    "compliance_lookup": [
        DataSource.COMPLIANCE_RECORDS,
        DataSource.PDF_DOCUMENTS,
        DataSource.PUBLIC_POLICIES,
    ],
    "audit_investigation": [
        DataSource.AUDIT_LOGS,
        DataSource.MONITORING_LOGS,
    ],
    "operational_analytics": [
        DataSource.SYSTEM_METRICS,
        DataSource.OPERATIONAL_DATASETS,
        DataSource.INFRASTRUCTURE_REPORTS,
        DataSource.MONITORING_LOGS,
    ],
    "finance_query": [
        DataSource.FINANCIAL_DATABASE,
        DataSource.INVOICE_RECORDS,
        DataSource.BUDGET_REPORTS,
    ],
    "technical_support": [
        DataSource.INFRASTRUCTURE_REPORTS,
        DataSource.MONITORING_LOGS,
        DataSource.INTERNAL_DOCUMENTATION,
    ],
    "policy_lookup": [
        DataSource.PUBLIC_POLICIES,
        DataSource.INTERNAL_DOCUMENTATION,
        DataSource.PDF_DOCUMENTS,
    ],
    "general_inquiry": [
        DataSource.PUBLIC_POLICIES,
        DataSource.INTERNAL_DOCUMENTATION,
        DataSource.PDF_DOCUMENTS,
    ],
}

SENSITIVE_KEYWORDS: dict[str, DataSource] = {
    "salary": DataSource.SALARY_RECORDS,
    "compensation": DataSource.SALARY_RECORDS,
    "executive pay": DataSource.SALARY_RECORDS,
    "payroll": DataSource.SALARY_RECORDS,
    "invoice": DataSource.INVOICE_RECORDS,
    "vendor payment": DataSource.INVOICE_RECORDS,
    "budget": DataSource.BUDGET_REPORTS,
    "audit log": DataSource.AUDIT_LOGS,
    "failed login": DataSource.AUDIT_LOGS,
    "compliance": DataSource.COMPLIANCE_RECORDS,
    "gdpr": DataSource.COMPLIANCE_RECORDS,
    "cpu": DataSource.SYSTEM_METRICS,
    "server": DataSource.SYSTEM_METRICS,
    "infrastructure": DataSource.INFRASTRUCTURE_REPORTS,
}


class RBACEngine:
    def get_permissions(self, role: UserRole) -> set[DataSource]:
        return ROLE_PERMISSIONS.get(role, set())

    def can_access(self, role: UserRole, source: DataSource) -> bool:
        return source in self.get_permissions(role)

    def filter_sources(self, role: UserRole, sources: list[DataSource]) -> list[DataSource]:
        permissions = self.get_permissions(role)
        return [s for s in sources if s in permissions]

    def check_query_access(
        self, role: UserRole, required_sources: list[DataSource]
    ) -> tuple[bool, DataSource | None]:
        permissions = self.get_permissions(role)
        denied = [s for s in required_sources if s not in permissions]
        if denied:
            return False, denied[0]
        return True, None

    def infer_required_sources(self, query: str) -> list[DataSource]:
        query_lower = query.lower()
        matched: set[DataSource] = set()
        for keyword, source in SENSITIVE_KEYWORDS.items():
            if keyword in query_lower:
                matched.add(source)
        return list(matched) if matched else []
