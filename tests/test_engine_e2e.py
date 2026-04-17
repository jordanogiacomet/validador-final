"""End-to-end validation engine tests.

Exercises the full pipeline (normalize -> derive flags -> run rules -> issues)
with real registered rules rather than synthetic test rules. Guards the
contract US-023 requires: the engine must turn raw display-named rows into
structured issues via canonical normalization, flag derivation, and rule
execution driven by tenant configuration.
"""

from app.core.engine import ValidationEngine
from app.core.registry import RULE_REGISTRY, register_rule
from app.core.tenant_config import CategoryConfig, TenantConfig
from app.core.validation_scope import ValidationScope
from app.rules.category_rules import CategoryCriticalCheckRule
from app.rules.integrity import DuplicateItemRule, FlagConsistencyRule
from app.rules.zero_item_quality import ZeroItemQualityRule


def setup_function():
    RULE_REGISTRY.clear()
    register_rule(DuplicateItemRule())
    register_rule(FlagConsistencyRule())
    register_rule(ZeroItemQualityRule())
    register_rule(CategoryCriticalCheckRule())


def teardown_function():
    RULE_REGISTRY.clear()


def _base_tenant(**overrides) -> TenantConfig:
    defaults = {
        "tenant_id": "e2e",
        "display_name": "E2E Tenant",
        "columns": {
            "item": "Item",
            "placa_anterior": "Placa Anterior",
            "descricao": "Descrição",
            "marca": "Marca",
            "modelo": "Modelo",
            "complemento": "Complemento",
        },
        "enabled_rules": [
            "duplicate_item",
            "flag_consistency",
            "zero_item_quality",
        ],
        "thresholds": {"short_complement_max_words": 3},
    }
    defaults.update(overrides)
    return TenantConfig(**defaults)


def _codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def test_e2e_clean_collected_row_produces_no_issues():
    tenant = _base_tenant()
    engine = ValidationEngine(tenant)

    raw_rows = [
        {
            "Item": "A001",
            "Placa Anterior": "OLD-001",
            "Descrição": "Notebook",
            "Marca": "Dell",
            "Modelo": "Latitude 7490",
            "Complemento": "i7 16GB 512GB SSD",
        }
    ]

    results = engine.validate_all(raw_rows, validation_scope=ValidationScope.ALL_ITEMS)

    assert results[0] == []


def test_e2e_zero_item_produces_zero_item_issues_only():
    tenant = _base_tenant()
    engine = ValidationEngine(tenant)

    raw_rows = [
        {
            "Item": "A001",
            "Placa Anterior": "",
            "Descrição": "Mesa",
            "Marca": "",
            "Modelo": "",
            "Complemento": "",
        }
    ]

    results = engine.validate_all(raw_rows)

    assert 0 in results
    codes = _codes(results[0])
    assert "ZERO_ITEM_COMPLEMENTO_EMPTY" in codes
    assert "ZERO_ITEM_MARCA_MISSING" in codes
    assert "ZERO_ITEM_MODELO_MISSING" in codes
    severities = {issue.severity for issue in results[0]}
    assert severities == {"warning"}


def test_e2e_detects_duplicate_items_across_rows():
    tenant = _base_tenant()
    engine = ValidationEngine(tenant)

    raw_rows = [
        {
            "Item": "DUP-1",
            "Placa Anterior": "OLD-1",
            "Descrição": "Monitor",
            "Marca": "LG",
            "Modelo": "24MP",
            "Complemento": "24 polegadas FHD",
        },
        {
            "Item": "DUP-1",
            "Placa Anterior": "OLD-2",
            "Descrição": "Monitor",
            "Marca": "LG",
            "Modelo": "24MP",
            "Complemento": "24 polegadas FHD",
        },
    ]

    results = engine.validate_all(raw_rows, validation_scope=ValidationScope.ALL_ITEMS)

    assert "DUPLICATE_ITEM" in _codes(results[0])
    assert "DUPLICATE_ITEM" in _codes(results[1])


def test_e2e_flag_derivation_drives_flag_consistency_rule():
    tenant = _base_tenant(enabled_rules=["flag_consistency"])
    engine = ValidationEngine(tenant)

    # Raw row has no Placa Anterior. The engine must derive
    # flag_item_cadastrado_do_zero=1 during normalization and
    # flag_consistency must accept it without raising any issue.
    raw_rows = [
        {
            "Item": "Z-1",
            "Placa Anterior": "",
            "Descrição": "Cadeira",
            "Marca": "Flexform",
            "Modelo": "Giratória",
            "Complemento": "Ergonômica com rodízios",
        }
    ]

    results = engine.validate_all(raw_rows, validation_scope=ValidationScope.ALL_ITEMS)

    assert results[0] == []


def test_e2e_respects_tenant_column_mapping_and_thresholds():
    tenant = _base_tenant(
        columns={
            "item": "codigo",
            "placa_anterior": "placa_antiga",
            "descricao": "especie",
            "marca": "fabricante",
            "modelo": "modelo",
            "complemento": "observacoes",
        },
        thresholds={"short_complement_max_words": 5},
    )
    engine = ValidationEngine(tenant)

    raw_rows = [
        {
            "codigo": "A001",
            "placa_antiga": "",
            "especie": "Mesa de escritório",
            "fabricante": "Giroflex",
            "modelo": "Alfa",
            "observacoes": "madeira branca",
        }
    ]

    results = engine.validate_all(raw_rows)

    codes = _codes(results[0])
    assert "ZERO_ITEM_COMPLEMENTO_SHORT" in codes


def test_e2e_category_critical_check_emits_error_for_missing_pattern():
    tenant = _base_tenant(
        enabled_rules=["category_critical_check"],
        categories=[
            CategoryConfig(
                name="ar_condicionado",
                display_name="AR CONDICIONADO",
                keywords=["ar condicionado", "split"],
                critical_checks=["btu_pattern"],
            )
        ],
    )
    engine = ValidationEngine(tenant)

    raw_rows = [
        {
            "Item": "AC-1",
            "Placa Anterior": "",
            "Descrição": "AR CONDICIONADO SPLIT",
            "Marca": "Electrolux",
            "Modelo": "VI12F",
            "Complemento": "quente e frio",
        }
    ]

    results = engine.validate_all(raw_rows, validation_scope=ValidationScope.ALL_ITEMS)

    issues = results[0]
    assert any(issue.severity == "error" for issue in issues)
    assert any(
        issue.code == "CATEGORY_AR_CONDICIONADO_BTU_PATTERN_MISSING"
        for issue in issues
    )


def test_e2e_category_critical_check_passes_when_pattern_present():
    tenant = _base_tenant(
        enabled_rules=["category_critical_check"],
        categories=[
            CategoryConfig(
                name="tv",
                keywords=["televis", "tv"],
                critical_checks=["inches_pattern"],
            )
        ],
    )
    engine = ValidationEngine(tenant)

    raw_rows = [
        {
            "Item": "TV-1",
            "Placa Anterior": "",
            "Descrição": "Televisor",
            "Marca": "Samsung",
            "Modelo": "QN55",
            "Complemento": "55 polegadas 4K",
        }
    ]

    results = engine.validate_all(raw_rows, validation_scope=ValidationScope.ALL_ITEMS)

    assert results[0] == []


def test_e2e_issues_are_structured_and_scoped_per_row():
    tenant = _base_tenant()
    engine = ValidationEngine(tenant)

    raw_rows = [
        # Row 0: collected, clean
        {
            "Item": "C-1",
            "Placa Anterior": "OLD-1",
            "Descrição": "Notebook",
            "Marca": "Dell",
            "Modelo": "7490",
            "Complemento": "i7 16GB 512GB SSD",
        },
        # Row 1: zero-created, bad quality
        {
            "Item": "Z-1",
            "Placa Anterior": "",
            "Descrição": "Armário",
            "Marca": "",
            "Modelo": "",
            "Complemento": "",
        },
    ]

    results = engine.validate_all(raw_rows, validation_scope=ValidationScope.ALL_ITEMS)

    assert results[0] == []
    assert results[1], "zero-created row must produce at least one issue"

    for issue in results[1]:
        assert issue.code
        assert issue.severity in {"error", "warning", "info"}
        assert issue.message
        assert issue.field is not None


def test_e2e_duplicate_scope_only_validates_duplicate_rows():
    tenant = _base_tenant()
    engine = ValidationEngine(tenant)

    raw_rows = [
        {"Item": "DUP", "Placa Anterior": "OLD", "Descrição": "Monitor"},
        {"Item": "UNIQUE", "Placa Anterior": "OLD", "Descrição": "Monitor"},
        {"Item": "DUP", "Placa Anterior": "OLD-2", "Descrição": "Monitor"},
    ]

    results = engine.validate_all(
        raw_rows,
        validation_scope=ValidationScope.DUPLICATE_ITEMS,
    )

    assert set(results.keys()) == {0, 2}
    assert "DUPLICATE_ITEM" in _codes(results[0])
    assert "DUPLICATE_ITEM" in _codes(results[2])


def test_e2e_default_scope_only_validates_zero_items():
    tenant = _base_tenant()
    engine = ValidationEngine(tenant)

    raw_rows = [
        {
            "Item": "C-1",
            "Placa Anterior": "OLD-1",
            "Descrição": "Notebook",
            "Marca": "Dell",
            "Modelo": "7490",
            "Complemento": "i7 16GB 512GB SSD",
        },
        {
            "Item": "Z-1",
            "Placa Anterior": "",
            "Descrição": "Armário",
            "Marca": "",
            "Modelo": "",
            "Complemento": "",
        },
    ]

    results = engine.validate_all(raw_rows)

    assert list(results.keys()) == [1]
    assert _codes(results[1])
