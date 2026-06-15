"""Query routing to appropriate data sources."""

from app.auth.rbac import INTENT_DEFAULT_SOURCES, RBACEngine
from app.intent.classifier import IntentResult
from app.models.domain import DataSource, UserRole


class QueryRouter:
    def __init__(self, rbac: RBACEngine | None = None):
        self.rbac = rbac or RBACEngine()

    def route(self, intent_result: IntentResult, role: UserRole, query: str) -> list[DataSource]:
        intent_key = intent_result.intent.value
        default_sources = INTENT_DEFAULT_SOURCES.get(intent_key, [])
        inferred = self.rbac.infer_required_sources(query)

        combined: list[DataSource] = []
        seen: set[DataSource] = set()
        for source in inferred + default_sources:
            if source not in seen:
                seen.add(source)
                combined.append(source)

        return self.rbac.filter_sources(role, combined)
