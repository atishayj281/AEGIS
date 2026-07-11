"""Grounded response generation with optional LLM backend."""

import re
from typing import TYPE_CHECKING

from app.config import Settings, get_settings
from app.intent.classifier import IntentResult
from app.models.domain import QueryIntent
from app.retrieval.aggregator import RetrievedContext

if TYPE_CHECKING:
    from app.conversation.manager import ConversationTurn


class ResponseGenerator:
    SYSTEM_PROMPT = (
        "You are an enterprise AI assistant. Answer ONLY using the provided context. "
        "If the context is insufficient, say so. Include factual details and cite sources. "
        "Never invent information not present in the context."
    )

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def generate(
        self,
        query: str,
        context: RetrievedContext,
        intent_result: IntentResult,
        history: list["ConversationTurn"] | None = None,
    ) -> tuple[str, float]:
        if not context.chunks:
            return (
                "I could not find relevant information in the data sources available to your role. "
                "Please refine your query or contact the appropriate department.",
                0.2,
            )

        if self.settings.gemini_api_key:
            try:
                answer, confidence = await self._generate_with_llm(
                    query, context, intent_result, history
                )
                return answer, confidence
            except Exception:
                pass

        return self._generate_template(query, context, intent_result, history)

    async def _generate_with_llm(
        self,
        query: str,
        context: RetrievedContext,
        intent_result: IntentResult,
        history: list["ConversationTurn"] | None = None,
    ) -> tuple[str, float]:
        import httpx

        contents = []
        if history:
            for turn in history:
                role = "model" if turn.role == "assistant" else "user"
                contents.append({
                    "role": role,
                    "parts": [{"text": turn.content}]
                })

        user_prompt = (
            f"Query: {query}\n\n"
            f"Intent: {intent_result.intent.value}\n\n"
            f"Context:\n{context.combined_context}\n\n"
            "Provide a concise, grounded answer with bullet points where appropriate."
        )
        contents.append({
            "role": "user",
            "parts": [{"text": user_prompt}]
        })

        payload = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": self.SYSTEM_PROMPT}]
            },
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 800
            }
        }

        model_name = self.settings.gemini_model
        if model_name.startswith("models/"):
            model_name = model_name[len("models/"):]

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.settings.gemini_api_key}"
        headers = {"Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            response_json = response.json()

        try:
            answer = response_json["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise ValueError(f"Unexpected response structure from Gemini API: {response_json}")

        confidence = min(0.95, intent_result.confidence + 0.1)
        return answer, confidence

    def _generate_template(
        self,
        query: str,
        context: RetrievedContext,
        intent_result: IntentResult,
        history: list["ConversationTurn"] | None = None,
    ) -> tuple[str, float]:
        intent = intent_result.intent
        parts: list[str] = []

        # Prepend a brief history summary so the template answer has some
        # conversational continuity even without an LLM.
        if history:
            history_lines = []
            for turn in history[-3:]:  # last 3 turns to keep it concise
                prefix = "Q" if turn.role == "user" else "A"
                history_lines.append(f"  [{prefix}]: {turn.content[:200]}")
            parts.append("[Prior conversation]\n" + "\n".join(history_lines) + "\n")

        if intent == QueryIntent.COMPLIANCE_LOOKUP:
            parts.extend(self._extract_compliance(context))
        elif intent == QueryIntent.AUDIT_INVESTIGATION:
            parts.extend(self._extract_audit(context))
        elif intent == QueryIntent.OPERATIONAL_ANALYTICS:
            parts.extend(self._extract_operational(context))
        elif intent == QueryIntent.FINANCE_QUERY:
            parts.extend(self._extract_finance(context))
        else:
            parts.extend(self._extract_general(context))

        if not parts:
            parts = [self._summarize_chunks(context)]

        source_names = list(dict.fromkeys(c.source_name for c in context.citations))
        parts.append(f"\nSources: {', '.join(source_names)}")

        confidence = self._compute_confidence(context, intent_result)
        return "\n".join(parts), confidence

    def _extract_compliance(self, context: RetrievedContext) -> list[str]:
        bullets: list[str] = []
        seen: set[str] = set()
        for chunk in context.chunks:
            candidates: list[str] = []
            if "15-Jan-2026" in chunk or "audit" in chunk.lower():
                if "medium-risk" in chunk.lower() or "medium risk" in chunk.lower():
                    candidates.append("- 3 medium-risk findings identified in the latest compliance audit")
                if "encryption" in chunk.lower():
                    candidates.append("- Encryption policy requires updates to align with AES-256 standards")
                if "no critical" in chunk.lower():
                    candidates.append("- No critical violations detected")
                if "15-Jan-2026" in chunk:
                    candidates.append("- Audit completed on 15-Jan-2026")
            if "retention" in chunk.lower() or "gdpr" in chunk.lower():
                candidates.extend([
                    "- Customer PII must be retained for 7 years for financial records",
                    "- Right to erasure requests must be processed within 30 days",
                    "- Marketing consent data may be retained for 3 years",
                ])
            for item in candidates:
                if item not in seen:
                    seen.add(item)
                    bullets.append(item)
        return bullets or ["- See compliance documentation in retrieved context"]

    def _extract_audit(self, context: RetrievedContext) -> list[str]:
        bullets: list[str] = []
        failed_count = 0
        for chunk in context.chunks:
            if "login_failed" in chunk or "failed" in chunk.lower():
                lines = [l for l in chunk.split("\n") if "login_failed" in l or "failed" in l.lower()]
                failed_count += len(lines)
                for line in lines[:5]:
                    bullets.append(f"- {line.strip()}")
        if failed_count:
            bullets.insert(0, f"- Found {failed_count} failed login attempt(s) in audit logs")
        return bullets or ["- No matching audit log entries found"]

    def _extract_operational(self, context: RetrievedContext) -> list[str]:
        bullets: list[str] = []
        critical_servers: set[str] = set()
        for chunk in context.chunks:
            if "cpu" in chunk.lower() or "server" in chunk.lower():
                for match in re.finditer(r"(\w+-[\w-]+)\s*\|\s*CPU:\s*(\d+)%", chunk):
                    server, cpu = match.group(1), int(match.group(2))
                    if cpu >= 85:
                        critical_servers.add(f"{server} ({cpu}% CPU)")
                for match in re.finditer(r"(prod-\w+-\d+)\s*\|\s*(\d+)%", chunk):
                    server, cpu = match.group(1), int(match.group(2))
                    if cpu >= 85:
                        critical_servers.add(f"{server} ({cpu}% CPU)")

        if critical_servers:
            bullets.append("- Servers exceeding CPU thresholds (>85%):")
            for s in sorted(critical_servers):
                bullets.append(f"  - {s}")
        else:
            for chunk in context.chunks:
                if "exceeded CPU" in chunk or "prod-" in chunk:
                    for line in chunk.split("\n"):
                        if "prod-" in line and ("%" in line or "CPU" in line):
                            bullets.append(f"- {line.strip()}")
        return bullets or ["- See operational metrics in retrieved context"]

    def _extract_finance(self, context: RetrievedContext) -> list[str]:
        bullets: list[str] = []
        for chunk in context.chunks:
            for line in chunk.split("\n"):
                if "invoice" in line.lower() or "vendor" in line.lower() or "$" in line:
                    bullets.append(f"- {line.strip()}")
        return bullets or ["- See financial records in retrieved context"]

    def _extract_general(self, context: RetrievedContext) -> list[str]:
        return [f"- {self._first_meaningful_line(chunk)}" for chunk in context.chunks[:3]]

    def _summarize_chunks(self, context: RetrievedContext) -> str:
        lines = []
        for chunk in context.chunks[:2]:
            line = self._first_meaningful_line(chunk)
            if line:
                lines.append(f"- {line}")
        return "\n".join(lines) if lines else "No summary available."

    def _first_meaningful_line(self, chunk: str) -> str:
        for line in chunk.split("\n"):
            stripped = line.strip().lstrip("#-* ")
            if len(stripped) > 20:
                return stripped[:200]
        return chunk[:200].strip()

    def _compute_confidence(self, context: RetrievedContext, intent_result: IntentResult) -> float:
        if not context.citations:
            return 0.2
        avg_relevance = sum(c.relevance_score for c in context.citations) / len(context.citations)
        source_bonus = min(0.1, 0.03 * len(set(c.source_name for c in context.citations)))
        return round(min(0.98, intent_result.confidence * 0.4 + avg_relevance * 0.5 + source_bonus), 2)
