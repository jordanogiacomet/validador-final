import time
from collections.abc import Callable
from dataclasses import dataclass

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
CancellationCheckpoint = Callable[[], None]
PARALLEL_SAFE_RULE_NAMES = frozenset({"llm_audit"})
CHECKPOINT_INTERVAL = 1000


def _maybe_run_checkpoint(
    checkpoint: CancellationCheckpoint | None,
    offset: int,
) -> None:
    if checkpoint is not None and offset % CHECKPOINT_INTERVAL == 0:
        checkpoint()


@dataclass(frozen=True)
class ValidationExecutionPlan:
    serial_rule_names: tuple[str, ...]
    parallel_rule_names: tuple[str, ...] = ()
    parallel_workers: int = 1


class ValidationEngine:
    def __init__(self, tenant: TenantConfig) -> None:
        self.tenant = tenant
        self.brand_model_normalizer = BrandModelNormalizer.from_config(
            tenant.normalization
        )

    def get_enabled_rules(
        self,
        rule_names: tuple[str, ...] | list[str] | None = None,
    ) -> list[BaseRule]:
        rules: list[BaseRule] = []
        selected_rule_names = (
            self.tenant.enabled_rules if rule_names is None else rule_names
        )

        for rule_name in selected_rule_names:
            if rule_name in self.tenant.disabled_rules:
                continue

            rule = RULE_REGISTRY.get(rule_name)
            if rule is not None:
                rules.append(rule)

        return rules

    def build_execution_plan(
        self,
        *,
        scoped_row_count: int,
    ) -> ValidationExecutionPlan:
        enabled_rule_names = tuple(rule.name for rule in self.get_enabled_rules())
        parallel_rule_names: tuple[str, ...] = ()
        parallel_workers = 1

        if (
            scoped_row_count > 1
            and self.tenant.llm.enabled
            and self.tenant.llm.parallel_requests > 1
        ):
            parallel_rule_names = tuple(
                rule_name
                for rule_name in enabled_rule_names
                if rule_name in PARALLEL_SAFE_RULE_NAMES
            )
            if parallel_rule_names:
                parallel_workers = min(
                    scoped_row_count,
                    self.tenant.llm.parallel_requests,
                )

        serial_rule_names = tuple(
            rule_name
            for rule_name in enabled_rule_names
            if rule_name not in parallel_rule_names
        )
        return ValidationExecutionPlan(
            serial_rule_names=serial_rule_names,
            parallel_rule_names=parallel_rule_names,
            parallel_workers=parallel_workers,
        )

    def validate_row(
        self,
        row_index: int,
        normalized_row: dict[str, str | int | float | None],
        raw_row: dict[str, object] | None = None,
        all_rows: list[dict[str, str | int | float | None]] | None = None,
        shared_context: dict | None = None,
        rule_names: tuple[str, ...] | list[str] | None = None,
        cancellation_checkpoint: CancellationCheckpoint | None = None,
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

        for rule in self.get_enabled_rules(rule_names=rule_names):
            if cancellation_checkpoint is not None:
                cancellation_checkpoint()
            if rule.applies(context):
                started_at = time.perf_counter()
                rule_issues = rule.validate(context)
                if cancellation_checkpoint is not None:
                    cancellation_checkpoint()
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
        cancellation_checkpoint: CancellationCheckpoint | None = None,
    ) -> list[RowType]:
        normalized_rows: list[RowType] = []
        for offset, row in enumerate(raw_rows):
            _maybe_run_checkpoint(cancellation_checkpoint, offset)
            normalized_rows.append(
                normalize_row(
                    row,
                    self.tenant.columns,
                    self.brand_model_normalizer,
                )
            )

        if cancellation_checkpoint is not None:
            cancellation_checkpoint()
        return normalized_rows

    def normalize_row(
        self,
        row: dict[str, object],
        cancellation_checkpoint: CancellationCheckpoint | None = None,
    ) -> RowType:
        if cancellation_checkpoint is not None:
            cancellation_checkpoint()
        normalized_row = normalize_row(
            row,
            self.tenant.columns,
            self.brand_model_normalizer,
        )
        if cancellation_checkpoint is not None:
            cancellation_checkpoint()
        return normalized_row

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
        cancellation_checkpoint: CancellationCheckpoint | None = None,
    ) -> list[int]:
        if validation_scope == ValidationScope.DUPLICATE_ITEMS:
            return get_duplicate_item_row_indices(
                normalized_rows,
                checkpoint=cancellation_checkpoint,
            )

        scoped_indices: list[int] = []
        for offset, normalized_row in enumerate(normalized_rows):
            _maybe_run_checkpoint(cancellation_checkpoint, offset)
            if self.is_row_in_scope(normalized_row, validation_scope=validation_scope):
                scoped_indices.append(offset)

        if cancellation_checkpoint is not None:
            cancellation_checkpoint()
        return scoped_indices

    def validate_normalized_rows(
        self,
        normalized_rows: list[RowType],
        raw_rows: list[dict[str, object]] | None = None,
        validation_scope: ValidationScope = DEFAULT_VALIDATION_SCOPE,
        rule_names: tuple[str, ...] | list[str] | None = None,
        cancellation_checkpoint: CancellationCheckpoint | None = None,
    ) -> dict[int, list[ValidationIssue]]:
        scope_row_indices = self.get_scoped_row_indices(
            normalized_rows,
            validation_scope=validation_scope,
            cancellation_checkpoint=cancellation_checkpoint,
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
                rule_names=rule_names,
                cancellation_checkpoint=cancellation_checkpoint,
            )
            results[idx] = issues

        return results

    def validate_all(
        self,
        raw_rows: list[dict[str, object]],
        validation_scope: ValidationScope = DEFAULT_VALIDATION_SCOPE,
        rule_names: tuple[str, ...] | list[str] | None = None,
        cancellation_checkpoint: CancellationCheckpoint | None = None,
    ) -> dict[int, list[ValidationIssue]]:
        normalized_rows = self.normalize_rows(
            raw_rows,
            cancellation_checkpoint=cancellation_checkpoint,
        )
        return self.validate_normalized_rows(
            normalized_rows,
            raw_rows=raw_rows,
            validation_scope=validation_scope,
            rule_names=rule_names,
            cancellation_checkpoint=cancellation_checkpoint,
        )
