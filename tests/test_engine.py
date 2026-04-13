from app.core.context import ValidationContext
from app.core.engine import ValidationEngine
from app.core.issue import ValidationIssue
from app.core.registry import RULE_REGISTRY, register_rule
from app.core.tenant_config import TenantConfig
from app.rules.base import BaseRule


class AlwaysFailRule(BaseRule):
    name: str = "always_fail"

    def applies(self, context: ValidationContext) -> bool:
        return True

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        return [
            ValidationIssue(
                code="TEST_FAIL",
                severity="error",
                message="Always fails",
                field="item",
            )
        ]


class NeverAppliesRule(BaseRule):
    name: str = "never_applies"

    def applies(self, context: ValidationContext) -> bool:
        return False

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        return [
            ValidationIssue(
                code="UNREACHABLE",
                severity="error",
                message="Should not appear",
            )
        ]


class RequiresDescricaoRule(BaseRule):
    name: str = "requires_descricao"

    def applies(self, context: ValidationContext) -> bool:
        return context.normalized_row.get("descricao") is not None

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        return [
            ValidationIssue(
                code="HAS_DESCRICAO",
                severity="info",
                message=str(context.normalized_row.get("descricao")),
                field="descricao",
            )
        ]


def _make_tenant(**overrides) -> TenantConfig:
    defaults = {
        "tenant_id": "test",
        "display_name": "Test Tenant",
        "enabled_rules": [],
    }
    defaults.update(overrides)
    return TenantConfig(**defaults)


def setup_function():
    RULE_REGISTRY.clear()


def teardown_function():
    RULE_REGISTRY.clear()


def test_register_and_get_enabled_rules():
    rule = AlwaysFailRule()
    register_rule(rule)

    tenant = _make_tenant(enabled_rules=["always_fail"])
    engine = ValidationEngine(tenant)
    enabled = engine.get_enabled_rules()

    assert len(enabled) == 1
    assert enabled[0].name == "always_fail"


def test_disabled_rules_are_excluded():
    rule = AlwaysFailRule()
    register_rule(rule)

    tenant = _make_tenant(
        enabled_rules=["always_fail"],
        disabled_rules=["always_fail"],
    )
    engine = ValidationEngine(tenant)
    assert engine.get_enabled_rules() == []


def test_unknown_rule_names_are_skipped():
    tenant = _make_tenant(enabled_rules=["nonexistent_rule"])
    engine = ValidationEngine(tenant)
    assert engine.get_enabled_rules() == []


def test_validate_row_returns_issues():
    register_rule(AlwaysFailRule())

    tenant = _make_tenant(enabled_rules=["always_fail"])
    engine = ValidationEngine(tenant)

    issues = engine.validate_row(
        row_index=0,
        normalized_row={"item": "001"},
    )

    assert len(issues) == 1
    assert issues[0].code == "TEST_FAIL"
    assert issues[0].severity == "error"
    assert issues[0].field == "item"


def test_validate_row_skips_non_applicable_rules():
    register_rule(NeverAppliesRule())

    tenant = _make_tenant(enabled_rules=["never_applies"])
    engine = ValidationEngine(tenant)

    issues = engine.validate_row(
        row_index=0,
        normalized_row={"item": "001"},
    )

    assert issues == []


def test_validate_row_no_rules():
    tenant = _make_tenant(enabled_rules=[])
    engine = ValidationEngine(tenant)

    issues = engine.validate_row(row_index=0, normalized_row={"item": "001"})
    assert issues == []


def test_validate_row_persists_shared_context_mutations():
    class SharedContextRule(BaseRule):
        name: str = "shared_context_rule"

        def applies(self, context: ValidationContext) -> bool:
            return True

        def validate(self, context: ValidationContext) -> list[ValidationIssue]:
            context.shared_context["seen_rows"] = context.shared_context.get("seen_rows", 0) + 1
            return []

    register_rule(SharedContextRule())

    tenant = _make_tenant(enabled_rules=["shared_context_rule"])
    engine = ValidationEngine(tenant)
    shared_context: dict[str, int] = {}

    engine.validate_row(
        row_index=0,
        normalized_row={"item": "001"},
        shared_context=shared_context,
    )
    engine.validate_row(
        row_index=1,
        normalized_row={"item": "002"},
        shared_context=shared_context,
    )

    assert shared_context["seen_rows"] == 2


def test_validate_all_processes_all_rows():
    register_rule(AlwaysFailRule())

    tenant = _make_tenant(enabled_rules=["always_fail"])
    engine = ValidationEngine(tenant)

    raw_rows = [
        {"Item": "001", "Placa Anterior": "ABC"},
        {"Item": "002", "Placa Anterior": ""},
    ]

    results = engine.validate_all(raw_rows)

    assert len(results) == 2
    assert len(results[0]) == 1
    assert len(results[1]) == 1


def test_validate_all_normalizes_rows():
    register_rule(AlwaysFailRule())

    tenant = _make_tenant(enabled_rules=["always_fail"])
    engine = ValidationEngine(tenant)

    raw_rows = [{"Item": "001", "Placa Anterior": "ABC"}]
    results = engine.validate_all(raw_rows)

    assert 0 in results


def test_validate_all_uses_tenant_column_mapping():
    register_rule(RequiresDescricaoRule())

    tenant = _make_tenant(
        enabled_rules=["requires_descricao"],
        columns={"descricao": "Espécie"},
    )
    engine = ValidationEngine(tenant)

    raw_rows = [{"Espécie": "MESA", "Complemento": "02 tomadas 500x600x800"}]
    results = engine.validate_all(raw_rows)

    assert results[0][0].code == "HAS_DESCRICAO"
    assert results[0][0].message == "MESA"


def test_validate_row_passes_all_rows_in_context():
    class CheckAllRowsRule(BaseRule):
        name: str = "check_all_rows"

        def applies(self, context: ValidationContext) -> bool:
            return True

        def validate(self, context: ValidationContext) -> list[ValidationIssue]:
            if len(context.all_rows) > 1:
                return [
                    ValidationIssue(
                        code="MULTI_ROW",
                        severity="info",
                        message=f"Has {len(context.all_rows)} rows",
                    )
                ]
            return []

    register_rule(CheckAllRowsRule())

    tenant = _make_tenant(enabled_rules=["check_all_rows"])
    engine = ValidationEngine(tenant)

    raw_rows = [
        {"Item": "001", "Placa Anterior": "A"},
        {"Item": "002", "Placa Anterior": "B"},
    ]

    results = engine.validate_all(raw_rows)
    assert results[0][0].code == "MULTI_ROW"


def test_validation_context_has_required_fields():
    tenant = _make_tenant()
    ctx = ValidationContext(
        tenant=tenant,
        row_index=0,
        normalized_row={"item": "001"},
        all_rows=[{"item": "001"}, {"item": "002"}],
        shared_context={"key": "value"},
    )

    assert ctx.tenant.tenant_id == "test"
    assert ctx.row_index == 0
    assert ctx.normalized_row["item"] == "001"
    assert len(ctx.all_rows) == 2
    assert ctx.shared_context["key"] == "value"
