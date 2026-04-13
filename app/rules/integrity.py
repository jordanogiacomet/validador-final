from collections import Counter

from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.rules.base import BaseRule


class DuplicateItemRule(BaseRule):
    name: str = "duplicate_item"

    def applies(self, context: ValidationContext) -> bool:
        return context.normalized_row.get("item") is not None

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        current_item = context.normalized_row.get("item")
        if current_item is None:
            return []

        if "_duplicate_item_counts" not in context.shared_context:
            counts: Counter[object] = Counter()
            for row in context.all_rows:
                val = row.get("item")
                if val is not None:
                    counts[val] += 1
            context.shared_context["_duplicate_item_counts"] = counts

        counts = context.shared_context["_duplicate_item_counts"]
        if counts[current_item] > 1:
            return [
                ValidationIssue(
                    code="DUPLICATE_ITEM",
                    severity="error",
                    message=f"Item '{current_item}' aparece {counts[current_item]} vezes",
                    field="item",
                )
            ]
        return []


class FlagConsistencyRule(BaseRule):
    name: str = "flag_consistency"

    def applies(self, context: ValidationContext) -> bool:
        return True

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        row = context.normalized_row
        placa = row.get("placa_anterior")
        coletado = row.get("flag_item_coletado")
        zero = row.get("flag_item_cadastrado_do_zero")

        issues: list[ValidationIssue] = []

        has_placa = bool(placa and str(placa).strip())

        if has_placa and coletado != 1:
            issues.append(
                ValidationIssue(
                    code="FLAG_CONSISTENCY_COLETADO",
                    severity="error",
                    message="Placa Anterior presente mas flag_item_coletado não é 1",
                    field="flag_item_coletado",
                )
            )

        if not has_placa and zero != 1:
            issues.append(
                ValidationIssue(
                    code="FLAG_CONSISTENCY_ZERO",
                    severity="error",
                    message="Placa Anterior ausente mas flag_item_cadastrado_do_zero não é 1",
                    field="flag_item_cadastrado_do_zero",
                )
            )

        if has_placa and zero == 1:
            issues.append(
                ValidationIssue(
                    code="FLAG_CONSISTENCY_CONFLICT",
                    severity="error",
                    message="Placa Anterior presente mas flag_item_cadastrado_do_zero é 1",
                    field="flag_item_cadastrado_do_zero",
                )
            )

        if not has_placa and coletado == 1:
            issues.append(
                ValidationIssue(
                    code="FLAG_CONSISTENCY_CONFLICT",
                    severity="error",
                    message="Placa Anterior ausente mas flag_item_coletado é 1",
                    field="flag_item_coletado",
                )
            )

        return issues
