"""Sensitive data masking for responses and retrieved content."""

import re
from dataclasses import dataclass, field

MASKING_RULES: list[tuple[str, str]] = [
    (r"(?i)(api[_-]?key\s*[=:]\s*)([^\s,;\"']+)", r"\1************"),
    (r"(?i)(password\s*[=:]\s*)([^\s,;\"']+)", r"\1************"),
    (r"(?i)(token\s*[=:]\s*)([^\s,;\"']+)", r"\1************"),
    (r"(?i)(secret\s*[=:]\s*)([^\s,;\"']+)", r"\1************"),
    (r"(?i)(bearer\s+)([A-Za-z0-9\-_.]+)", r"\1************"),
    (r"\b(\d{3})-(\d{2})-(\d{4})\b", r"XXX-XX-\3"),
    (r"\b(\d{3})(\d{2})(\d{4})\b", r"XXX-XX-\3"),
    (r"(?i)(ssn\s*[=:]\s*)(?![X*])([^\s,;\"']+)", r"\1XXX-XX-****"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL_REDACTED]"),
    (r"(?i)(sk-prod-[A-Za-z0-9\-]+)", "sk-prod-************"),
    (r"(?i)(sk_live_[A-Za-z0-9]+)", "sk_live_************"),
]


@dataclass
class MaskingResult:
    text: str
    masked_fields: list[str] = field(default_factory=list)


class DataMasker:
    FIELD_LABELS = {
        "api_key": "API Key",
        "password": "Password",
        "token": "Token",
        "secret": "Secret",
        "ssn": "SSN",
        "email": "Email",
    }

    def mask(self, text: str) -> MaskingResult:
        masked_fields: list[str] = []
        result = text

        for pattern, replacement in MASKING_RULES:
            new_result, count = re.subn(pattern, replacement, result)
            if count > 0:
                label = self._label_for_pattern(pattern)
                if label and label not in masked_fields:
                    masked_fields.append(label)
                result = new_result

        return MaskingResult(text=result, masked_fields=masked_fields)

    def _label_for_pattern(self, pattern: str) -> str | None:
        pattern_lower = pattern.lower()
        for key, label in self.FIELD_LABELS.items():
            if key.replace("_", "") in pattern_lower.replace("_", ""):
                return label
        if "email" in pattern_lower:
            return "Email"
        if "ssn" in pattern_lower:
            return "SSN"
        return "Sensitive Data"
