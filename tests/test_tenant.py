import pytest

from app.core.tenant_config import (
    DEFAULT_ISSUED_API_KEY_TTL_SECONDS,
    APIKeyConfig,
    AuthConfig,
    CategoryConfig,
    CSVConfig,
    LLMConfig,
    NormalizationConfig,
    OperatorConfig,
    OperatorRole,
    SuspiciousPatternsConfig,
    TenantConfig,
)
from app.core.tenant_loader import (
    list_tenants,
    load_default_tenant_config,
    load_tenant_config,
    resolve_tenant_api_key,
)


class TestTenantConfig:
    def test_minimal_config(self) -> None:
        config = TenantConfig(tenant_id="test", display_name="Test")
        assert config.tenant_id == "test"
        assert config.aliases == []
        assert config.disabled is False
        assert config.columns == {}
        assert config.enabled_rules == []
        assert config.disabled_rules == []
        assert config.thresholds == {}
        assert config.categories == []
        assert config.normalization.brand_aliases == {}
        assert config.normalization.model_aliases == {}
        assert config.normalization.model_brands == {}
        assert config.suspicious_patterns.literal_patterns == []
        assert config.suspicious_patterns.regex_patterns == []
        assert config.csv.delimiter == ","
        assert config.csv.encoding == "utf-8"
        assert config.llm.enabled is False
        assert config.llm.fallback_model is None
        assert config.llm.parallel_requests == 1
        assert config.llm.cache_ttl_seconds == 0
        assert config.auth.issued_api_key_ttl_seconds == DEFAULT_ISSUED_API_KEY_TTL_SECONDS
        assert config.api_keys == []
        assert config.operators == []

    def test_config_with_categories(self) -> None:
        config = TenantConfig(
            tenant_id="t",
            display_name="T",
            categories=[
                CategoryConfig(
                    name="ar_condicionado",
                    display_name="AR CONDICIONADO",
                    keywords=["ar condicionado", "split"],
                    critical_checks=["btu_pattern"],
                    required_fields=["complemento"],
                    field_help={"complemento": "capacidade 18000 btus"},
                )
            ],
        )
        assert len(config.categories) == 1
        assert config.categories[0].name == "ar_condicionado"
        assert config.categories[0].display_name == "AR CONDICIONADO"
        assert "btu_pattern" in config.categories[0].critical_checks
        assert "complemento" in config.categories[0].required_fields
        assert config.categories[0].field_help["complemento"] == "capacidade 18000 btus"

    def test_config_with_llm(self) -> None:
        config = TenantConfig(
            tenant_id="t",
            display_name="T",
            llm=LLMConfig(
                enabled=True,
                model="claude-sonnet-4-20250514",
                fallback_model="claude-haiku-4-20250514",
                parallel_requests=3,
                cache_ttl_seconds=300,
            ),
        )
        assert config.llm.enabled is True
        assert config.llm.model == "claude-sonnet-4-20250514"
        assert config.llm.fallback_model == "claude-haiku-4-20250514"
        assert config.llm.parallel_requests == 3
        assert config.llm.cache_ttl_seconds == 300

    def test_config_with_csv_options(self) -> None:
        config = TenantConfig(
            tenant_id="t",
            display_name="T",
            csv=CSVConfig(delimiter=";", encoding="iso-8859-1"),
        )
        assert config.csv.delimiter == ";"
        assert config.csv.encoding == "iso-8859-1"

    def test_config_with_normalization_aliases(self) -> None:
        config = TenantConfig(
            tenant_id="t",
            display_name="T",
            normalization=NormalizationConfig(
                brand_aliases={"samsúng": "Samsung"},
                model_aliases={"thinkpad t14 g1": "ThinkPad T14 Gen 1"},
                model_brands={"ThinkPad T14 Gen 1": "Lenovo"},
            ),
        )
        assert config.normalization.brand_aliases["samsúng"] == "Samsung"
        assert (
            config.normalization.model_aliases["thinkpad t14 g1"]
            == "ThinkPad T14 Gen 1"
        )
        assert config.normalization.model_brands["ThinkPad T14 Gen 1"] == "Lenovo"

    def test_config_with_api_keys(self) -> None:
        config = TenantConfig(
            tenant_id="t",
            display_name="T",
            api_keys=[APIKeyConfig(key_id="tenant-local", value="secret-value")],
        )
        assert config.api_keys[0].key_id == "tenant-local"
        assert config.api_keys[0].value == "secret-value"

    def test_config_with_operators(self) -> None:
        config = TenantConfig(
            tenant_id="t",
            display_name="T",
            operators=[
                OperatorConfig(
                    operator_id="operator-1",
                    username="operator",
                    password_hash="pbkdf2_sha256$1$salt$digest",
                )
            ],
        )
        assert config.operators[0].operator_id == "operator-1"
        assert config.operators[0].username == "operator"
        assert config.operators[0].role is OperatorRole.TENANT_ADMIN
        assert config.operators[0].disabled is False

    def test_config_with_auth_policy(self) -> None:
        config = TenantConfig(
            tenant_id="t",
            display_name="T",
            auth=AuthConfig(issued_api_key_ttl_seconds=1800),
        )
        assert config.auth.issued_api_key_ttl_seconds == 1800

    def test_config_with_suspicious_patterns(self) -> None:
        config = TenantConfig(
            tenant_id="t",
            display_name="T",
            suspicious_patterns=SuspiciousPatternsConfig(
                literal_patterns=["diversos", "teste"],
                regex_patterns=[r"\bnao\s+informado\b"],
            ),
        )
        assert config.suspicious_patterns.literal_patterns == ["diversos", "teste"]
        assert config.suspicious_patterns.regex_patterns == [r"\bnao\s+informado\b"]


class TestTenantLoader:
    def test_load_default_tenant(self) -> None:
        config = load_default_tenant_config()
        assert config.tenant_id == "default"
        assert config.display_name == "Default Tenant"
        assert config.llm.enabled is False
        assert config.suspicious_patterns.literal_patterns == []
        assert config.api_keys[0].key_id == "default-local"
        assert config.operators[0].operator_id == "default-local-operator"
        assert config.operators[0].role is OperatorRole.TENANT_ADMIN
        assert config.auth.issued_api_key_ttl_seconds == 28800

    def test_load_default_by_id(self) -> None:
        config = load_tenant_config("default")
        assert config.tenant_id == "default"

    def test_load_empresa_exemplo(self) -> None:
        config = load_tenant_config("empresa_exemplo")
        assert config.tenant_id == "empresa_exemplo"
        assert len(config.categories) == 2
        assert config.normalization.brand_aliases["samsúng"] == "Samsung"
        assert (
            config.normalization.model_aliases["thinkpad t14 g1"]
            == "ThinkPad T14 Gen 1"
        )
        assert config.normalization.model_brands["ThinkPad T14 Gen 1"] == "Lenovo"
        assert config.llm.enabled is True
        assert config.llm.fallback_model is None
        assert config.llm.parallel_requests == 4
        assert config.llm.cache_ttl_seconds == 86400
        assert config.auth.issued_api_key_ttl_seconds == DEFAULT_ISSUED_API_KEY_TTL_SECONDS
        assert config.thresholds["short_complement_max_words"] == 5

    def test_load_redesim(self) -> None:
        config = load_tenant_config("redesim")
        assert config.tenant_id == "redesim"
        assert config.display_name == "RedeSim"
        assert config.aliases == ["redesim_v2"]
        assert config.csv.delimiter == ";"
        assert config.csv.encoding == "iso-8859-1"
        assert config.columns["item"] == "item"
        assert config.columns["placa_anterior"] == "item_anterior"
        assert config.columns["descricao"] == "descricao"
        assert "category_required_fields" in config.enabled_rules
        assert len(config.categories) > 5
        monitor = next(cat for cat in config.categories if cat.name == "monitor")
        assert "complemento" in monitor.required_fields
        assert "inches_pattern" in monitor.critical_checks
        assert monitor.field_help["complemento"] == "LED 19 POL"

    def test_load_redesim_v2(self) -> None:
        config = load_tenant_config("redesim_v2")
        assert config.tenant_id == "redesim"
        assert config.display_name == "RedeSim"
        assert config.csv.delimiter == ";"
        assert config.csv.encoding == "iso-8859-1"
        assert config.columns["item"] == "item"
        assert config.columns["placa_anterior"] == "item_anterior"
        assert config.columns["descricao"] == "descricao"
        assert "category_required_fields" in config.enabled_rules
        assert len(config.categories) > 5

    def test_load_nonexistent_tenant_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_tenant_config("nonexistent_tenant_xyz")

    def test_list_tenants(self) -> None:
        tenants = list_tenants()
        assert "default" in tenants
        assert "empresa_exemplo" in tenants
        assert "redesim" in tenants
        assert "redesim_v2" not in tenants

    def test_default_tenant_has_columns(self) -> None:
        config = load_default_tenant_config()
        assert config.columns["item"] == "Item"
        assert config.columns["placa_anterior"] == "Placa Anterior"

    def test_resolve_tenant_api_key_returns_scoped_match(self) -> None:
        match = resolve_tenant_api_key("redesim-local-test-key")
        assert match is not None
        assert match.tenant.tenant_id == "redesim"
        assert match.api_key.key_id == "redesim-local"

    def test_resolve_legacy_redesim_v2_api_key_returns_canonical_match(self) -> None:
        match = resolve_tenant_api_key("redesim-v2-local-test-key")
        assert match is not None
        assert match.tenant.tenant_id == "redesim"
        assert match.api_key.key_id == "redesim-v2-local"

    def test_resolve_tenant_api_key_returns_none_for_unknown_value(self) -> None:
        assert resolve_tenant_api_key("missing-key") is None
