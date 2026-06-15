"""Intent classification for enterprise queries."""

import re
from dataclasses import dataclass

from app.models.domain import QueryDomain, QueryIntent

INTENT_PATTERNS: list[tuple[QueryIntent, QueryDomain, list[str]]] = [
    (
        QueryIntent.COMPLIANCE_LOOKUP,
        QueryDomain.COMPLIANCE,
        [
            r"compliance",
            r"gdpr",
            r"retention\s+policy",
            r"regulatory",
            r"data\s+protection",
            r"privacy",
            r"right\s+to\s+erasure",
        ],
    ),
    (
        QueryIntent.AUDIT_INVESTIGATION,
        QueryDomain.SECURITY,
        [
            r"audit",
            r"failed\s+login",
            r"login\s+attempt",
            r"security\s+incident",
            r"unauthorized\s+access",
            r"breach",
        ],
    ),
    (
        QueryIntent.OPERATIONAL_ANALYTICS,
        QueryDomain.OPERATIONS,
        [
            r"cpu",
            r"server",
            r"threshold",
            r"metrics",
            r"performance",
            r"monitoring",
            r"infrastructure",
            r"uptime",
        ],
    ),
    (
        QueryIntent.FINANCE_QUERY,
        QueryDomain.FINANCE,
        [
            r"invoice",
            r"vendor",
            r"budget",
            r"payment",
            r"financial",
            r"expense",
            r"revenue",
            r"salary",
            r"compensation",
            r"payroll",
        ],
    ),
    (
        QueryIntent.TECHNICAL_SUPPORT,
        QueryDomain.OPERATIONS,
        [
            r"incident",
            r"outage",
            r"error",
            r"deployment",
            r"technical\s+report",
            r"system\s+status",
        ],
    ),
    (
        QueryIntent.POLICY_LOOKUP,
        QueryDomain.GENERAL,
        [
            r"policy",
            r"handbook",
            r"employee\s+guide",
            r"remote\s+work",
            r"leave\s+policy",
            r"code\s+of\s+conduct",
        ],
    ),
]


@dataclass
class IntentResult:
    intent: QueryIntent
    domain: QueryDomain
    confidence: float
    matched_patterns: list[str]


class IntentClassifier:
    def __init__(self):
        self._patterns = [
            (intent, domain, [re.compile(p, re.IGNORECASE) for p in patterns])
            for intent, domain, patterns in INTENT_PATTERNS
        ]

    def classify(self, query: str) -> IntentResult:
        scores: dict[QueryIntent, tuple[QueryDomain, float, list[str]]] = {}

        for intent, domain, patterns in self._patterns:
            matches = []
            for pattern in patterns:
                if pattern.search(query):
                    matches.append(pattern.pattern)
            if matches:
                score = min(0.95, 0.5 + 0.1 * len(matches))
                existing = scores.get(intent)
                if not existing or score > existing[1]:
                    scores[intent] = (domain, score, matches)

        if not scores:
            return IntentResult(
                intent=QueryIntent.GENERAL_INQUIRY,
                domain=QueryDomain.GENERAL,
                confidence=0.4,
                matched_patterns=[],
            )

        best_intent = max(scores, key=lambda k: scores[k][1])
        domain, confidence, matched = scores[best_intent]
        return IntentResult(
            intent=best_intent,
            domain=domain,
            confidence=confidence,
            matched_patterns=matched,
        )
