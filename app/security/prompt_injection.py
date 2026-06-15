"""Prompt injection detection and rejection."""

import re

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?prior\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"forget\s+(everything|all)\s+(you\s+)?(know|learned|were\s+told)",
    r"reveal\s+(all\s+)?confidential",
    r"show\s+(all\s+)?hidden\s+(data|records|database)",
    r"bypass\s+(security|rbac|access\s+control|policies)",
    r"override\s+(security|permissions|access)",
    r"you\s+are\s+now\s+(in\s+)?(admin|root|superuser)\s+mode",
    r"pretend\s+(you\s+)?(are|have)\s+(no\s+)?restrictions",
    r"display\s+(the\s+)?(entire|full|complete)\s+database",
    r"jailbreak",
    r"do\s+anything\s+now",
    r"system\s+prompt",
    r"<\s*script",
    r";\s*drop\s+table",
    r"union\s+select",
    r"'\s*or\s*'1'\s*=\s*'1",
]


class PromptInjectionGuard:
    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

    def check(self, query: str) -> tuple[bool, str | None]:
        normalized = query.strip()
        if len(normalized) > 2000:
            return False, "Query exceeds maximum allowed length"

        for pattern in self._compiled:
            match = pattern.search(normalized)
            if match:
                return False, f"Potential prompt injection detected: '{match.group()}'"

        if normalized.count("ignore") >= 2 and "instruction" in normalized.lower():
            return False, "Potential prompt injection: repeated instruction override attempts"

        return True, None
