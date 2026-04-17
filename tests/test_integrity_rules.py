from app.core.context import ValidationContext
from app.core.registry import RULE_REGISTRY, register_rule
from app.core.tenant_config import TenantConfig
from app.rules.integrity import DuplicateItemRule, FlagConsistencyRule


def _make_tenant(**overrides) -> TenantConfig:
    defaults = {
        "tenant_id": "test",
        "display_name": "Test",
        "columns": {},
        "enabled_rules": ["duplicate_item", "flag_consistency"],
        "disabled_rules": [],
        "thresholds": {},
        "categories": [],
    }
    defaults.update(overrides)
    return TenantConfig(**defaults)


def _make_context(
    row: dict,
    all_rows: list[dict] | None = None,
    row_index: int = 0,
    shared_context: dict | None = None,
) -> ValidationContext:
    return ValidationContext(
        tenant=_make_tenant(),
        row_index=row_index,
        normalized_row=row,
        all_rows=all_rows or [row],
        shared_context=shared_context or {},
    )


def setup_function():
    RULE_REGISTRY.clear()


def teardown_function():
    RULE_REGISTRY.clear()


# --- DuplicateItemRule ---

class TestDuplicateItemRule:
    def test_applies_when_item_present(self):
        rule = DuplicateItemRule()
        ctx = _make_context({"item": "A001"})
        assert rule.applies(ctx) is True

    def test_not_applies_when_item_none(self):
        rule = DuplicateItemRule()
        ctx = _make_context({"item": None})
        assert rule.applies(ctx) is False

    def test_no_issue_for_unique_items(self):
        rule = DuplicateItemRule()
        rows = [
            {"item": "A001", "flag_item_coletado": 1, "flag_item_cadastrado_do_zero": 0},
            {"item": "A002", "flag_item_coletado": 1, "flag_item_cadastrado_do_zero": 0},
        ]
        ctx = _make_context(rows[0], all_rows=rows, row_index=0)
        assert rule.validate(ctx) == []

    def test_issue_for_duplicate_items(self):
        rule = DuplicateItemRule()
        rows = [
            {"item": "A001", "flag_item_coletado": 1, "flag_item_cadastrado_do_zero": 0},
            {"item": "A001", "flag_item_coletado": 1, "flag_item_cadastrado_do_zero": 0},
            {"item": "A002", "flag_item_coletado": 1, "flag_item_cadastrado_do_zero": 0},
        ]
        ctx = _make_context(rows[0], all_rows=rows, row_index=0)
        issues = rule.validate(ctx)
        assert len(issues) == 1
        assert issues[0].code == "DUPLICATE_ITEM"
        assert issues[0].severity == "error"
        assert issues[0].field == "item"
        assert "2 vezes" in issues[0].message

    def test_duplicate_count_cached_in_shared_context(self):
        rule = DuplicateItemRule()
        rows = [
            {"item": "A001"},
            {"item": "A001"},
        ]
        ctx0 = _make_context(rows[0], all_rows=rows, row_index=0)
        rule.validate(ctx0)
        assert "_duplicate_item_counts" in ctx0.shared_context

        ctx1 = _make_context(
            rows[1], all_rows=rows, row_index=1, shared_context=ctx0.shared_context
        )
        issues = rule.validate(ctx1)
        assert len(issues) == 1

    def test_no_duplicate_for_none_items(self):
        rule = DuplicateItemRule()
        rows = [{"item": None}, {"item": None}]
        ctx = _make_context(rows[0], all_rows=rows, row_index=0)
        assert rule.validate(ctx) == []


# --- FlagConsistencyRule ---

class TestFlagConsistencyRule:
    def test_applies_always(self):
        rule = FlagConsistencyRule()
        ctx = _make_context({})
        assert rule.applies(ctx) is True

    def test_consistent_collected_item(self):
        rule = FlagConsistencyRule()
        ctx = _make_context({
            "placa_anterior": "OLD-001",
            "flag_item_coletado": 1,
            "flag_item_cadastrado_do_zero": 0,
        })
        assert rule.validate(ctx) == []

    def test_consistent_zero_item(self):
        rule = FlagConsistencyRule()
        ctx = _make_context({
            "placa_anterior": None,
            "flag_item_coletado": 0,
            "flag_item_cadastrado_do_zero": 1,
        })
        assert rule.validate(ctx) == []

    def test_placa_present_but_coletado_wrong(self):
        rule = FlagConsistencyRule()
        ctx = _make_context({
            "placa_anterior": "OLD-001",
            "flag_item_coletado": 0,
            "flag_item_cadastrado_do_zero": 0,
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "FLAG_CONSISTENCY_COLETADO" in codes

    def test_placa_absent_but_zero_wrong(self):
        rule = FlagConsistencyRule()
        ctx = _make_context({
            "placa_anterior": None,
            "flag_item_coletado": 0,
            "flag_item_cadastrado_do_zero": 0,
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "FLAG_CONSISTENCY_ZERO" in codes

    def test_placa_present_but_zero_flag_set(self):
        rule = FlagConsistencyRule()
        ctx = _make_context({
            "placa_anterior": "OLD-001",
            "flag_item_coletado": 1,
            "flag_item_cadastrado_do_zero": 1,
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "FLAG_CONSISTENCY_CONFLICT" in codes

    def test_placa_absent_but_coletado_flag_set(self):
        rule = FlagConsistencyRule()
        ctx = _make_context({
            "placa_anterior": None,
            "flag_item_coletado": 1,
            "flag_item_cadastrado_do_zero": 1,
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "FLAG_CONSISTENCY_CONFLICT" in codes

    def test_empty_string_placa_treated_as_absent(self):
        rule = FlagConsistencyRule()
        ctx = _make_context({
            "placa_anterior": "   ",
            "flag_item_coletado": 0,
            "flag_item_cadastrado_do_zero": 1,
        })
        assert rule.validate(ctx) == []

    def test_issue_fields_populated(self):
        rule = FlagConsistencyRule()
        ctx = _make_context({
            "placa_anterior": "OLD-001",
            "flag_item_coletado": 0,
            "flag_item_cadastrado_do_zero": 0,
        })
        issues = rule.validate(ctx)
        for issue in issues:
            assert issue.code
            assert issue.severity
            assert issue.message
            assert issue.field


# --- Integration with engine ---

class TestIntegrityRulesWithEngine:
    def test_rules_register_and_run(self):
        from app.core.engine import ValidationEngine
        from app.core.validation_scope import ValidationScope

        register_rule(DuplicateItemRule())
        register_rule(FlagConsistencyRule())

        tenant = _make_tenant()
        engine = ValidationEngine(tenant=tenant)

        raw_rows = [
            {"Item": "A001", "Placa Anterior": "OLD-001"},
            {"Item": "A001", "Placa Anterior": ""},
        ]
        results = engine.validate_all(
            raw_rows,
            validation_scope=ValidationScope.ALL_ITEMS,
        )

        assert 0 in results
        assert 1 in results

        row0_codes = [i.code for i in results[0]]
        assert "DUPLICATE_ITEM" in row0_codes

        row1_codes = [i.code for i in results[1]]
        assert "DUPLICATE_ITEM" in row1_codes
