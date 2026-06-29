"""Role-Based Access Control engine."""

from app.models.domain import DataSource
from datetime import datetime, timezone
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ROLE_PERMISSIONS_V2 = {
    "org_admin":           {"*"},
    "team_lead":           {"*"},
    "compliance_officer":  {"compliance_records", "audit_logs", "public_policies"},
    "finance_analyst":     {"financial_db", "financial_database", "invoice_records", "public_policies"},
    "operations_engineer": {"audit_logs", "system_metrics", "public_policies"},
    "employee":            {"public_policies"},
    "guest":               set(),
}

async def resolve_access(
    ctx: dict,
    data_source_type: str,
    team_id: str | None = None,
    data_source_id: str | None = None,
) -> bool:
    db: AsyncSession = ctx.get("db")
    user_id = ctx.get("user_id")
    
    if not db or not user_id:
        return False

    now = datetime.now(timezone.utc)

    def to_uuid(val):
        if not val:
            return None
        if isinstance(val, uuid.UUID):
            return val
        return uuid.UUID(str(val))

    try:
        user_uuid = to_uuid(user_id)
        team_uuid = to_uuid(team_id)
        ds_uuid = to_uuid(data_source_id)
    except ValueError:
        return False

    # Step 2 & 3 & 4: Check team memberships
    if team_uuid:
        stmt = text(
            "SELECT role, expires_at FROM team_memberships "
            "WHERE user_id = :user_id AND team_id = :team_id"
        )
        result = await db.execute(stmt, {"user_id": user_uuid, "team_id": team_uuid})
        membership = result.fetchone()
        
        if membership:
            role, expires_at = membership
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < now:
                    return False
            
            allowed_sources = ROLE_PERMISSIONS_V2.get(role, set())
            if "*" in allowed_sources or data_source_type in allowed_sources:
                return True
    else:
        stmt = text(
            "SELECT role, expires_at FROM team_memberships "
            "WHERE user_id = :user_id"
        )
        result = await db.execute(stmt, {"user_id": user_uuid})
        memberships = result.fetchall()
        
        for role, expires_at in memberships:
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < now:
                    continue
            
            allowed_sources = ROLE_PERMISSIONS_V2.get(role, set())
            if "*" in allowed_sources or data_source_type in allowed_sources:
                return True

    # Step 5: Fallback to resource_grants
    if ds_uuid:
        stmt = text(
            "SELECT expires_at FROM resource_grants "
            "WHERE user_id = :user_id AND data_source_id = :data_source_id"
        )
        result = await db.execute(stmt, {"user_id": user_uuid, "data_source_id": ds_uuid})
        grant = result.fetchone()
        
        if grant:
            expires_at = grant[0]
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < now:
                    return False
            return True

    return False



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


def infer_required_sources(query: str) -> list[DataSource]:
    query_lower = query.lower()
    matched: set[DataSource] = set()
    for keyword, source in SENSITIVE_KEYWORDS.items():
        if keyword in query_lower:
            matched.add(source)
    return list(matched) if matched else []



