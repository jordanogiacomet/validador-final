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

CRITICAL_CHECK_LABELS: dict[str, str] = {
    "btu_pattern": "capacidade em BTU",
    "inches_pattern": "polegadas",
    "ports_pattern": "quantidade de portas",
    "channels_pattern": "quantidade de canais",
    "liters_pattern": "capacidade em litros",
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

DEFAULT_CRITICAL_CHECK_FIELDS = ["complemento"]


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


def get_critical_check_label(check_name: str) -> str:
    return CRITICAL_CHECK_LABELS.get(check_name, "detalhe técnico obrigatório")


def get_critical_check_fields(category: CategoryConfig, check_name: str) -> list[str]:
    configured_fields = category.critical_check_fields.get(check_name)
    if configured_fields:
        return configured_fields
    return DEFAULT_CRITICAL_CHECK_FIELDS


def join_field_labels(field_names: list[str]) -> str:
    labels = [FIELD_LABELS.get(field_name, field_name) for field_name in field_names]
    if not labels:
        return "Revisão geral"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} ou {labels[1]}"
    return f"{', '.join(labels[:-1])} ou {labels[-1]}"


class CategoryCriticalCheckRule(BaseRule):
    name: str = "category_critical_check"

    def applies(self, context: ValidationContext) -> bool:
        cat = get_matching_category(context)
        return cat is not None and len(cat.critical_checks) > 0

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        row = context.normalized_row
        cat = get_matching_category(context)
        if cat is None:
            return []

        issues: list[ValidationIssue] = []
        for check_name in cat.critical_checks:
            pattern = CRITICAL_CHECK_PATTERNS.get(check_name)
            if pattern is None:
                continue
            target_fields = get_critical_check_fields(cat, check_name)
            searchable_text = " ".join(
                str(row.get(field_name, "")).strip()
                for field_name in target_fields
                if row.get(field_name)
            )
            if not pattern.search(searchable_text):
                category_label = get_category_label(cat)
                requirement_label = get_critical_check_label(check_name)
                target_label = join_field_labels(target_fields)
                issues.append(
                    ValidationIssue(
                        code=f"CATEGORY_{cat.name.upper()}_{check_name.upper()}_MISSING",
                        severity="error",
                        message=(
                            f"Espécie '{category_label}': informar {requirement_label}"
                            f" em {target_label}"
                        ),
                        field="complemento" if "complemento" in target_fields else target_fields[0],
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
