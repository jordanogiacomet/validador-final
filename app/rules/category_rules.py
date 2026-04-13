import re

from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.core.tenant_config import CategoryConfig
from app.rules.base import BaseRule

BTU_PATTERN = re.compile(r"\d+\s*(?:btu|btus)", re.IGNORECASE)
INCHES_PATTERN = re.compile(r"\d+\s*(?:pol|polegadas?|\")", re.IGNORECASE)

CRITICAL_CHECK_PATTERNS: dict[str, re.Pattern[str]] = {
    "btu_pattern": BTU_PATTERN,
    "inches_pattern": INCHES_PATTERN,
}


def classify_category(
    descricao: str, categories: list[CategoryConfig]
) -> CategoryConfig | None:
    text = descricao.lower()
    for cat in categories:
        for keyword in cat.keywords:
            if keyword.lower() in text:
                return cat
    return None


class CategoryCriticalCheckRule(BaseRule):
    name: str = "category_critical_check"

    def applies(self, context: ValidationContext) -> bool:
        if not context.tenant.categories:
            return False
        descricao = context.normalized_row.get("descricao")
        if not descricao or not str(descricao).strip():
            return False
        cat = classify_category(str(descricao), context.tenant.categories)
        return cat is not None and len(cat.critical_checks) > 0

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        row = context.normalized_row
        descricao = str(row.get("descricao", ""))
        complemento = str(row.get("complemento", "")).strip() if row.get("complemento") else ""
        modelo = str(row.get("modelo", "")).strip() if row.get("modelo") else ""

        searchable_text = f"{descricao} {complemento} {modelo}"

        cat = classify_category(descricao, context.tenant.categories)
        if cat is None:
            return []

        issues: list[ValidationIssue] = []
        for check_name in cat.critical_checks:
            pattern = CRITICAL_CHECK_PATTERNS.get(check_name)
            if pattern is None:
                continue
            if not pattern.search(searchable_text):
                issues.append(
                    ValidationIssue(
                        code=f"CATEGORY_{cat.name.upper()}_{check_name.upper()}_MISSING",
                        severity="error",
                        message=(
                            f"Categoria '{cat.name}': padrão '{check_name}' não encontrado"
                            f" em Descrição/Complemento/Modelo"
                        ),
                        field="descricao",
                    )
                )
        return issues
