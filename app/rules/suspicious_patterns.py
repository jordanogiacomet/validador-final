import re
from dataclasses import dataclass

from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.core.normalization import normalize_lookup_key
from app.core.tenant_config import SuspiciousPatternsConfig
from app.rules.base import BaseRule

_MATCHER_CACHE_KEY = "_suspicious_pattern_matcher"
_FIELD_LABELS = {
    "descricao": "Descrição",
    "complemento": "Complemento",
}


@dataclass(frozen=True)
class SuspiciousPatternMatcher:
    literal_patterns: tuple[tuple[str, str], ...]
    regex_patterns: tuple[tuple[str, re.Pattern[str]], ...]

    @classmethod
    def from_config(
        cls,
        config: SuspiciousPatternsConfig,
    ) -> "SuspiciousPatternMatcher":
        literal_patterns = tuple(
            (normalize_lookup_key(pattern), pattern.strip())
            for pattern in config.literal_patterns
            if pattern.strip()
        )
        regex_patterns = tuple(
            (pattern.strip(), re.compile(pattern, re.IGNORECASE))
            for pattern in config.regex_patterns
            if pattern.strip()
        )
        return cls(
            literal_patterns=literal_patterns,
            regex_patterns=regex_patterns,
        )

    def find_match(self, value: str) -> tuple[str, str] | None:
        normalized_value = normalize_lookup_key(value)
        for normalized_pattern, original_pattern in self.literal_patterns:
            if normalized_pattern and normalized_pattern in normalized_value:
                return ("literal", original_pattern)

        for original_pattern, compiled_pattern in self.regex_patterns:
            if compiled_pattern.search(value):
                return ("regex", original_pattern)

        return None


class SuspiciousPatternRule(BaseRule):
    name: str = "suspicious_pattern"

    def applies(self, context: ValidationContext) -> bool:
        config = context.tenant.suspicious_patterns
        return any(pattern.strip() for pattern in config.literal_patterns) or any(
            pattern.strip() for pattern in config.regex_patterns
        )

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        matcher = self._get_matcher(context)
        issues: list[ValidationIssue] = []

        for field_name in ("descricao", "complemento"):
            value = context.normalized_row.get(field_name)
            if not value or not str(value).strip():
                continue

            match = matcher.find_match(str(value))
            if match is None:
                continue

            match_type, pattern = match
            field_label = _FIELD_LABELS[field_name]
            issues.append(
                ValidationIssue(
                    code="SUSPICIOUS_PATTERN_DETECTED",
                    severity="warning",
                    message=(
                        f"{field_label} contém padrão suspeito "
                        f"({match_type}: '{pattern}')"
                    ),
                    field=field_name,
                )
            )

        return issues

    def _get_matcher(self, context: ValidationContext) -> SuspiciousPatternMatcher:
        cached_matcher = context.shared_context.get(_MATCHER_CACHE_KEY)
        if isinstance(cached_matcher, SuspiciousPatternMatcher):
            return cached_matcher

        matcher = SuspiciousPatternMatcher.from_config(context.tenant.suspicious_patterns)
        context.shared_context[_MATCHER_CACHE_KEY] = matcher
        return matcher
