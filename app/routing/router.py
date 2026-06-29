from app.auth.rbac import INTENT_DEFAULT_SOURCES, infer_required_sources, resolve_access
from app.intent.classifier import IntentResult
from app.models.domain import DataSource


class QueryRouter:
    def __init__(self, rbac=None):
        pass

    async def route(self, intent_result: IntentResult, ctx: dict, query: str, team_id: str | None = None) -> list[DataSource]:
        intent_key = intent_result.intent.value
        default_sources = INTENT_DEFAULT_SOURCES.get(intent_key, [])
        inferred = infer_required_sources(query)

        combined: list[DataSource] = []
        seen: set[DataSource] = set()
        for source in inferred + default_sources:
            if source not in seen:
                seen.add(source)
                combined.append(source)

        allowed_sources = []
        for source in combined:
            if await resolve_access(ctx, source.value, team_id=team_id):
                allowed_sources.append(source)
        return allowed_sources
