"""Main RAG pipeline orchestrator."""

import time
import uuid
from datetime import datetime, timezone

from app.auth.jwt_auth import User
from app.auth.rbac import infer_required_sources, resolve_access
from sqlalchemy.ext.asyncio import AsyncSession
from app.generation.response_generator import ResponseGenerator
from app.intent.classifier import IntentClassifier
from app.models.domain import DataSource
from app.models.schemas import (
    AccessDeniedResponse,
    AuditLogEntry,
    QueryResponse,
    SecurityViolationResponse,
)
from app.observability.audit_logger import AuditLogger
from app.retrieval.aggregator import ContextAggregator
from app.routing.router import QueryRouter
from app.security.data_masking import DataMasker
from app.security.prompt_injection import PromptInjectionGuard
from app.conversation.manager import ConversationManager, get_conversation_manager


class RAGPipeline:
    def __init__(
        self,
        intent_classifier: IntentClassifier | None = None,
        query_router: QueryRouter | None = None,
        aggregator: ContextAggregator | None = None,
        response_generator: ResponseGenerator | None = None,
        injection_guard: PromptInjectionGuard | None = None,
        data_masker: DataMasker | None = None,
        audit_logger: AuditLogger | None = None,
        conversation_manager: ConversationManager | None = None,
    ):
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.query_router = query_router or QueryRouter()
        self.aggregator = aggregator or ContextAggregator()
        self.response_generator = response_generator or ResponseGenerator()
        self.injection_guard = injection_guard or PromptInjectionGuard()
        self.data_masker = data_masker or DataMasker()
        self.audit_logger = audit_logger or AuditLogger()
        self.conversation_manager = conversation_manager or get_conversation_manager()

    async def process_query(
        self,
        query: str,
        user: User,
        db: AsyncSession,
        top_k: int = 5,
        session_id: str | None = None,
        team_id: str | None = None,
    ) -> QueryResponse | AccessDeniedResponse | SecurityViolationResponse:
        start = time.perf_counter()
        query_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc)

        # Resolve the role for the audit log if we can find one for the team_id
        effective_role = "employee"
        if team_id and user.roles:
            effective_role = user.roles.get(team_id, "employee")
        elif user.roles:
            effective_role = next(iter(user.roles.values()), "employee")

        # Retrieve conversation context
        session = await self.conversation_manager.get_or_create_session(session_id, user.username)
        history = await self.conversation_manager.get_history(session.session_id)
        conversation_turn = (len(session.turns) // 2) + 1

        # Step 1: Prompt injection check
        safe, reason = self.injection_guard.check(query)
        if not safe:
            await self.audit_logger.log_async(
                AuditLogEntry(
                    query_id=query_id,
                    username=user.username,
                    role=effective_role,
                    query=query,
                    outcome="blocked_security",
                    security_violation=True,
                    response_time_ms=round((time.perf_counter() - start) * 1000, 2),
                    timestamp=now,
                    metadata={"reason": reason},
                ),
                db,
                user.org_id,
            )
            return SecurityViolationResponse(
                query=query,
                reason=reason or "Security policy violation",
                violation_type="prompt_injection",
                query_id=query_id,
                timestamp=now,
            )

        # Step 2: Intent classification
        intent_result = self.intent_classifier.classify(query)

        print(f"Intent: {intent_result}")

        # Step 3: RBAC - check inferred sensitive sources
        inferred_sources = infer_required_sources(query)
        print(f"Inferred Source: {inferred_sources}")
        
        ctx = {
            "db": db,
            "user_id": user.db_id,
            "org_id": user.org_id,
            "roles": user.roles,
            "team_ids": user.team_ids,
        }

        if inferred_sources:
            for denied_source in inferred_sources:
                allowed = await resolve_access(ctx, denied_source.value, team_id=team_id)
                if not allowed:
                    await self.audit_logger.log_async(
                        AuditLogEntry(
                            query_id=query_id,
                            username=user.username,
                            role=effective_role,
                            query=query,
                            intent=intent_result.intent,
                            outcome="access_denied",
                            rbac_violation=True,
                            response_time_ms=round((time.perf_counter() - start) * 1000, 2),
                            timestamp=now,
                            metadata={"denied_source": denied_source.value},
                        ),
                        db,
                        user.org_id,
                    )
                    return AccessDeniedResponse(
                        query=query,
                        message=(
                            f"Access Denied: You do not have permission to access "
                            f"{denied_source.value.replace('_', ' ')}."
                        ),
                        required_permission=denied_source,
                        query_id=query_id,
                        timestamp=now,
                    )

        # Step 4: Route to data sources
        routed_sources = await self.query_router.route(intent_result, ctx, query, team_id=team_id)
        print(f"Route: {routed_sources}")
        if not routed_sources:
            await self.audit_logger.log_async(
                AuditLogEntry(
                    query_id=query_id,
                    username=user.username,
                    role=effective_role,
                    query=query,
                    intent=intent_result.intent,
                    outcome="access_denied_no_sources",
                    rbac_violation=True,
                    response_time_ms=round((time.perf_counter() - start) * 1000, 2),
                    timestamp=now,
                ),
                db,
                user.org_id,
            )
            return AccessDeniedResponse(
                query=query,
                message="Access Denied: No data sources available for your role and query.",
                query_id=query_id,
                timestamp=now,
            )

        # Step 5: Hybrid retrieval — scoped to this user's org namespace
        context = self.aggregator.retrieve(query, routed_sources, org_id=user.org_id, top_k=top_k)
        print(f"Context: {context}")
        # Step 6: Grounded response
        answer, confidence = await self.response_generator.generate(
            query, context, intent_result, history=history
        )
        
        # Step 7: Mask sensitive data
        masked = self.data_masker.mask(answer)
        for chunk_idx, chunk in enumerate(context.chunks):
            chunk_masked = self.data_masker.mask(chunk)
            context.chunks[chunk_idx] = chunk_masked.text

        for citation in context.citations:
            citation_masked = self.data_masker.mask(citation.excerpt)
            citation.excerpt = citation_masked.text

        # Record this turn in the session history (safe, masked version)
        await self.conversation_manager.add_turn(session.session_id, "user", query)
        await self.conversation_manager.add_turn(session.session_id, "assistant", masked.text)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        await self.audit_logger.log_async(
            AuditLogEntry(
                query_id=query_id,
                username=user.username,
                role=effective_role,
                query=query,
                intent=intent_result.intent,
                outcome="success",
                response_time_ms=elapsed_ms,
                timestamp=now,
                metadata={
                    "sources": [s.value for s in routed_sources],
                    "citation_count": len(context.citations),
                    "confidence": confidence,
                },
            ),
            db,
            user.org_id,
        )

        return QueryResponse(
            query=query,
            answer=masked.text,
            intent=intent_result.intent,
            domain=intent_result.domain,
            confidence=confidence,
            citations=context.citations,
            retrieval_trace=context.traces,
            masked_fields=masked.masked_fields,
            query_id=query_id,
            response_time_ms=elapsed_ms,
            timestamp=now,
            session_id=session.session_id,
            conversation_turn=conversation_turn,
        )
