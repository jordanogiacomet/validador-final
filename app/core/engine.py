from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.core.registry import RULE_REGISTRY
from app.core.tenant_config import TenantConfig


class ValidationEngine:
    def __init__(self, tenant: TenantConfig) -> None:
        self.tenant = tenant

    def get_enabled_rules(self) -> list[object]:
        rules: list[object] = []

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
        shared_context: dict | None = None,
    ) -> list[ValidationIssue]:
        context = ValidationContext(
            tenant=self.tenant,
            row_index=row_index,
            normalized_row=normalized_row,
            shared_context=shared_context or {},
        )

        issues: list[ValidationIssue] = []

        for rule in self.get_enabled_rules():
            applies = getattr(rule, "applies", None)
            validate = getattr(rule, "validate", None)

            if callable(applies) and callable(validate) and applies(context):
                issues.extend(validate(context))

        return issues