import time

from app.core.canonical_fields import normalize_row
from app.core.context import ValidationContext
from app.core.duplicate_items import get_duplicate_item_row_indices
from app.core.issue import ValidationIssue
from app.core.metrics import record_rule_execution
from app.core.normalization import BrandModelNormalizer
from app.core.registry import RULE_REGISTRY
from app.core.tenant_config import TenantConfig
from app.core.validation_scope import DEFAULT_VALIDATION_SCOPE, ValidationScope
from app.rules.base import BaseRule

RowType = dict[str, str | int | float | None]


class ValidationEngine:
    def __init__(self, tenant: TenantConfig) -> None:
        self.tenant = tenant
        self.brand_model_normalizer = BrandModelNormalizer.from_config(
            tenant.normalization
        )

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
        raw_row: dict[str, object] | None = None,
        all_rows: list[dict[str, str | int | float | None]] | None = None,
        shared_context: dict | None = None,
    ) -> list[ValidationIssue]:
        source_shared_context = shared_context if shared_context is not None else {}
        context = ValidationContext(
            tenant=self.tenant,
            row_index=row_index,
            raw_row=raw_row or {},
            normalized_row=normalized_row,
            all_rows=all_rows or [],
            shared_context=source_shared_context,
        )

        issues: list[ValidationIssue] = []

        for rule in self.get_enabled_rules():
            if rule.applies(context):
                started_at = time.perf_counter()
                rule_issues = rule.validate(context)
                record_rule_execution(
                    self.tenant.tenant_id,
                    rule.name,
                    (time.perf_counter() - started_at) * 1000.0,
                    rule_issues,
                )
                issues.extend(rule_issues)

        if shared_context is not None:
            shared_context.clear()
            shared_context.update(context.shared_context)

        return issues

    def normalize_rows(
        self,
        raw_rows: list[dict[str, object]],
    ) -> list[RowType]:
        return [
            normalize_row(
                row,
                self.tenant.columns,
                self.brand_model_normalizer,
            )
            for row in raw_rows
        ]

    def is_row_in_scope(
        self,
        normalized_row: RowType,
        validation_scope: ValidationScope = DEFAULT_VALIDATION_SCOPE,
    ) -> bool:
        if validation_scope == ValidationScope.ALL_ITEMS:
            return True

        return normalized_row.get("flag_item_cadastrado_do_zero") == 1

    def get_scoped_row_indices(
        self,
        normalized_rows: list[RowType],
        validation_scope: ValidationScope = DEFAULT_VALIDATION_SCOPE,
    ) -> list[int]:
        if validation_scope == ValidationScope.DUPLICATE_ITEMS:
            return get_duplicate_item_row_indices(normalized_rows)

        return [
            idx
            for idx, normalized_row in enumerate(normalized_rows)
            if self.is_row_in_scope(normalized_row, validation_scope=validation_scope)
        ]

    def validate_normalized_rows(
        self,
        normalized_rows: list[RowType],
        raw_rows: list[dict[str, object]] | None = None,
        validation_scope: ValidationScope = DEFAULT_VALIDATION_SCOPE,
    ) -> dict[int, list[ValidationIssue]]:
        scope_row_indices = self.get_scoped_row_indices(
            normalized_rows,
            validation_scope=validation_scope,
        )
        scope_rows = [normalized_rows[idx] for idx in scope_row_indices]

        shared_context: dict = {}
        results: dict[int, list[ValidationIssue]] = {}
        for idx in scope_row_indices:
            issues = self.validate_row(
                row_index=idx,
                normalized_row=normalized_rows[idx],
                raw_row=raw_rows[idx] if raw_rows is not None else None,
                all_rows=scope_rows,
                shared_context=shared_context,
            )
            results[idx] = issues

        return results

    def validate_all(
        self,
        raw_rows: list[dict[str, object]],
        validation_scope: ValidationScope = DEFAULT_VALIDATION_SCOPE,
    ) -> dict[int, list[ValidationIssue]]:
        normalized_rows = self.normalize_rows(raw_rows)
        return self.validate_normalized_rows(
            normalized_rows,
            raw_rows=raw_rows,
            validation_scope=validation_scope,
        )
