from app.core.canonical_fields import normalize_row
from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.core.registry import RULE_REGISTRY
from app.core.tenant_config import TenantConfig
from app.rules.base import BaseRule

RowType = dict[str, str | int | float | None]


class ValidationEngine:
    def __init__(self, tenant: TenantConfig) -> None:
        self.tenant = tenant

    def get_enabled_rules(self) -> list[BaseRule]:
        rules: list[BaseRule] = []

        for rule_name in self.tenant.enabled_rules:
            if rule_name in self.tenant.disabled_rules:
                continue

            rule = RULE_REGISTRY.get(rule_name)
            if rule is not None:
                rules.append(rule)

        return rules

    def validate_row(
        self,
        row_index: int,
        normalized_row: dict[str, str | int | float | None],
        all_rows: list[dict[str, str | int | float | None]] | None = None,
        shared_context: dict | None = None,
    ) -> list[ValidationIssue]:
        source_shared_context = shared_context if shared_context is not None else {}
        context = ValidationContext(
            tenant=self.tenant,
            row_index=row_index,
            normalized_row=normalized_row,
            all_rows=all_rows or [],
            shared_context=source_shared_context,
        )

        issues: list[ValidationIssue] = []

        for rule in self.get_enabled_rules():
            if rule.applies(context):
                issues.extend(rule.validate(context))

        if shared_context is not None:
            shared_context.clear()
            shared_context.update(context.shared_context)

        return issues

    def normalize_rows(
        self,
        raw_rows: list[dict[str, object]],
    ) -> list[RowType]:
        return [normalize_row(row, self.tenant.columns) for row in raw_rows]

    def is_row_in_scope(self, normalized_row: RowType) -> bool:
        return normalized_row.get("flag_item_cadastrado_do_zero") == 1

    def get_scoped_row_indices(
        self,
        normalized_rows: list[RowType],
    ) -> list[int]:
        return [
            idx
            for idx, normalized_row in enumerate(normalized_rows)
            if self.is_row_in_scope(normalized_row)
        ]

    def validate_normalized_rows(
        self,
        normalized_rows: list[RowType],
    ) -> dict[int, list[ValidationIssue]]:
        scope_row_indices = self.get_scoped_row_indices(normalized_rows)
        scope_rows = [normalized_rows[idx] for idx in scope_row_indices]

        shared_context: dict = {}
        results: dict[int, list[ValidationIssue]] = {}
        for idx in scope_row_indices:
            issues = self.validate_row(
                row_index=idx,
                normalized_row=normalized_rows[idx],
                all_rows=scope_rows,
                shared_context=shared_context,
            )
            results[idx] = issues

        return results

    def validate_all(
        self,
        raw_rows: list[dict[str, object]],
    ) -> dict[int, list[ValidationIssue]]:
        normalized_rows = self.normalize_rows(raw_rows)
        return self.validate_normalized_rows(normalized_rows)
