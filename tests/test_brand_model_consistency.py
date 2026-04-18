from app.core.context import ValidationContext
from app.core.engine import ValidationEngine
from app.core.registry import RULE_REGISTRY, register_rule
from app.core.tenant_config import NormalizationConfig, TenantConfig
from app.rules.brand_model_consistency import BrandModelConsistencyRule


def setup_function() -> None:
    RULE_REGISTRY.clear()


def teardown_function() -> None:
    RULE_REGISTRY.clear()


def _tenant() -> TenantConfig:
    return TenantConfig(
        tenant_id="empresa_exemplo",
        display_name="Empresa Exemplo",
        enabled_rules=["brand_model_consistency"],
        normalization=NormalizationConfig(
            brand_aliases={"hewlett packard": "HP"},
            model_aliases={"élitebook 840 g5": "EliteBook 840 G5"},
            model_brands={"EliteBook 840 G5": "HP"},
        ),
    )


def _context(*, marca: str, modelo: str) -> ValidationContext:
    return ValidationContext(
        tenant=_tenant(),
        row_index=0,
        normalized_row={
            "marca": marca,
            "modelo": modelo,
        },
        shared_context={},
    )


def test_brand_model_consistency_rule_accepts_matching_brand() -> None:
    rule = BrandModelConsistencyRule()

    issues = rule.validate(_context(marca="HP", modelo="EliteBook 840 G5"))

    assert issues == []


def test_brand_model_consistency_rule_warns_on_mismatch() -> None:
    rule = BrandModelConsistencyRule()

    issues = rule.validate(_context(marca="Dell", modelo="EliteBook 840 G5"))

    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "BRAND_MODEL_CONSISTENCY_MISMATCH"
    assert issue.severity == "warning"
    assert issue.field == "marca"
    assert "HP" in issue.message
    assert "Dell" in issue.message


def test_brand_model_consistency_rule_is_silent_when_model_is_not_dictionary_backed() -> None:
    rule = BrandModelConsistencyRule()

    issues = rule.validate(_context(marca="Dell", modelo="Latitude 5400"))

    assert issues == []


def test_engine_applies_brand_model_consistency_rule_after_model_normalization() -> None:
    register_rule(BrandModelConsistencyRule())
    engine = ValidationEngine(_tenant())

    results = engine.validate_all(
        [
            {
                "Item": "001",
                "Placa Anterior": "",
                "Marca": "Dell",
                "Modelo": "ÉLITEBOOK 840 G5",
            }
        ]
    )

    assert len(results[0]) == 1
    issue = results[0][0]
    assert issue.code == "BRAND_MODEL_CONSISTENCY_MISMATCH"
    assert issue.field == "marca"
    assert "EliteBook 840 G5" in issue.message
