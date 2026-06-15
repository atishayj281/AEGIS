from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    COMPLIANCE_OFFICER = "compliance_officer"
    FINANCE_ANALYST = "finance_analyst"
    OPERATIONS_ENGINEER = "operations_engineer"
    EMPLOYEE = "employee"


class DataSource(str, Enum):
    PDF_DOCUMENTS = "pdf_documents"
    COMPLIANCE_RECORDS = "compliance_records"
    AUDIT_LOGS = "audit_logs"
    FINANCIAL_DATABASE = "financial_database"
    INVOICE_RECORDS = "invoice_records"
    BUDGET_REPORTS = "budget_reports"
    MONITORING_LOGS = "monitoring_logs"
    INFRASTRUCTURE_REPORTS = "infrastructure_reports"
    SYSTEM_METRICS = "system_metrics"
    OPERATIONAL_DATASETS = "operational_datasets"
    PUBLIC_POLICIES = "public_policies"
    INTERNAL_DOCUMENTATION = "internal_documentation"
    SALARY_RECORDS = "salary_records"


class QueryIntent(str, Enum):
    COMPLIANCE_LOOKUP = "compliance_lookup"
    AUDIT_INVESTIGATION = "audit_investigation"
    OPERATIONAL_ANALYTICS = "operational_analytics"
    FINANCE_QUERY = "finance_query"
    TECHNICAL_SUPPORT = "technical_support"
    POLICY_LOOKUP = "policy_lookup"
    GENERAL_INQUIRY = "general_inquiry"


class QueryDomain(str, Enum):
    COMPLIANCE = "compliance"
    SECURITY = "security"
    FINANCE = "finance"
    OPERATIONS = "operations"
    HR = "hr"
    GENERAL = "general"
