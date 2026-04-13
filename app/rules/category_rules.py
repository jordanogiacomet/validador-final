import re

from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.core.tenant_config import CategoryConfig
from app.rules.base import BaseRule

BTU_PATTERN = re.compile(r"\d+\s*(?:btu|btus)", re.IGNORECASE)
INCHES_PATTERN = re.compile(r"\d+\s*(?:pol|polegadas?|\")", re.IGNORECASE)
PORTS_PATTERN = re.compile(r"\d+\s*portas?", re.IGNORECASE)
CHANNELS_PATTERN = re.compile(r"\d+\s*canais?", re.IGNORECASE)
LITERS_PATTERN = re.compile(r"\d+\s*(?:l|litros?)\b", re.IGNORECASE)

CRITICAL_CHECK_PATTERNS: dict[str, re.Pattern[str]] = {
    "btu_pattern": BTU_PATTERN,
    "inches_pattern": INCHES_PATTERN,
    "ports_pattern": PORTS_PATTERN,
    "channels_pattern": CHANNELS_PATTERN,
    "liters_pattern": LITERS_PATTERN,
}

FIELD_LABELS: dict[str, str] = {
    "item": "Item",
    "placa_anterior": "Placa Anterior",
    "descricao": "Descrição",
    "marca": "Marca",
    "modelo": "Modelo",
    "ns": "NS",
    "local": "Local",
    "cc": "CC",
    "complemento": "Complemento",
    "observacao": "Observação",
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


def get_matching_category(context: ValidationContext) -> CategoryConfig | None:
    if not context.tenant.categories:
        return None

    descricao = context.normalized_row.get("descricao")
    if not descricao or not str(descricao).strip():
        return None

    return classify_category(str(descricao), context.tenant.categories)


def get_category_label(category: CategoryConfig) -> str:
    if category.display_name:
        return category.display_name
    return category.name.replace("_", " ").upper()


class CategoryCriticalCheckRule(BaseRule):
    name: str = "category_critical_check"

    def applies(self, context: ValidationContext) -> bool:
        cat = get_matching_category(context)
        return cat is not None and len(cat.critical_checks) > 0

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        row = context.normalized_row
        descricao = str(row.get("descricao", ""))
        complemento = str(row.get("complemento", "")).strip() if row.get("complemento") else ""
        modelo = str(row.get("modelo", "")).strip() if row.get("modelo") else ""

        searchable_text = f"{descricao} {complemento} {modelo}"

        cat = get_matching_category(context)
        if cat is None:
            return []

        issues: list[ValidationIssue] = []
        for check_name in cat.critical_checks:
            pattern = CRITICAL_CHECK_PATTERNS.get(check_name)
            if pattern is None:
                continue
            if not pattern.search(searchable_text):
                category_label = get_category_label(cat)
                issues.append(
                    ValidationIssue(
                        code=f"CATEGORY_{cat.name.upper()}_{check_name.upper()}_MISSING",
                        severity="error",
                        message=(
                            f"Categoria '{category_label}': padrão '{check_name}' não encontrado"
                            f" em Descrição/Complemento/Modelo"
                        ),
                        field="descricao",
                    )
                )
        return issues


class CategoryRequiredFieldsRule(BaseRule):
    name: str = "category_required_fields"

    def applies(self, context: ValidationContext) -> bool:
        cat = get_matching_category(context)
        return cat is not None and len(cat.required_fields) > 0

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        cat = get_matching_category(context)
        if cat is None:
            return []

        row = context.normalized_row
        issues: list[ValidationIssue] = []

        for field_name in cat.required_fields:
            value = row.get(field_name)
            if value and str(value).strip():
                continue

            field_label = FIELD_LABELS.get(field_name, field_name)
            help_text = cat.field_help.get(field_name)
            category_label = get_category_label(cat)
            message = f"Espécie '{category_label}': preencher {field_label}"
            if help_text:
                message = f"{message}. Ex.: {help_text}"

            issues.append(
                ValidationIssue(
                    code=f"CATEGORY_{cat.name.upper()}_{field_name.upper()}_REQUIRED",
                    severity="warning",
                    message=message,
                    field=field_name,
                )
            )

        return issues
