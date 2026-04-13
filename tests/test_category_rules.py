from app.core.context import ValidationContext
from app.core.registry import RULE_REGISTRY, register_rule
from app.core.tenant_config import CategoryConfig, TenantConfig
from app.rules.category_rules import (
    CategoryCriticalCheckRule,
    CategoryRequiredFieldsRule,
    classify_category,
)


def setup_function():
    RULE_REGISTRY.clear()


def teardown_function():
    RULE_REGISTRY.clear()


AC_CATEGORY = CategoryConfig(
    name="ar_condicionado",
    display_name="AR CONDICIONADO",
    keywords=["ar condicionado", "split", "ar-condicionado"],
    critical_checks=["btu_pattern"],
)

TV_CATEGORY = CategoryConfig(
    name="tv",
    display_name="TV",
    keywords=["televisor", "tv", "televisão"],
    critical_checks=["inches_pattern"],
)

SWITCH_CATEGORY = CategoryConfig(
    name="switch",
    display_name="SWITCH",
    keywords=["switch"],
    critical_checks=["ports_pattern"],
)

DVR_CATEGORY = CategoryConfig(
    name="dvr",
    display_name="DVR",
    keywords=["dvr"],
    critical_checks=["channels_pattern"],
)

TANK_CATEGORY = CategoryConfig(
    name="tanque_metalico",
    display_name="TANQUE METALICO",
    keywords=["tanque metalico"],
    critical_checks=["liters_pattern"],
)

MONITOR_CATEGORY = CategoryConfig(
    name="monitor",
    display_name="MONITOR",
    keywords=["monitor"],
    required_fields=["marca", "modelo", "complemento"],
    critical_checks=["inches_pattern"],
    field_help={"complemento": "LED 19 POL"},
)


def _make_tenant(
    categories: list[CategoryConfig] | None = None,
    enabled_rules: list[str] | None = None,
) -> TenantConfig:
    return TenantConfig(
        tenant_id="test",
        display_name="Test",
        enabled_rules=["category_critical_check"] if enabled_rules is None else enabled_rules,
        categories=[AC_CATEGORY, TV_CATEGORY] if categories is None else categories,
    )


def _make_context(
    row: dict,
    tenant: TenantConfig | None = None,
) -> ValidationContext:
    return ValidationContext(
        tenant=tenant or _make_tenant(),
        row_index=0,
        normalized_row=row,
    )


# --- classify_category tests ---


def test_classify_category_matches_keyword():
    cats = [AC_CATEGORY, TV_CATEGORY]
    assert classify_category("AR CONDICIONADO SPLIT 9000", cats) == AC_CATEGORY


def test_classify_category_case_insensitive():
    cats = [AC_CATEGORY, TV_CATEGORY]
    assert classify_category("Televisor Samsung", cats) == TV_CATEGORY


def test_classify_category_no_match():
    cats = [AC_CATEGORY, TV_CATEGORY]
    assert classify_category("Mesa de escritório", cats) is None


def test_classify_category_first_match_wins():
    combined = CategoryConfig(
        name="combo",
        display_name="COMBO",
        keywords=["tv"],
        critical_checks=[],
    )
    cats = [combined, TV_CATEGORY]
    result = classify_category("TV LED", cats)
    assert result == combined


# --- applies tests ---


def test_applies_true_when_category_matches():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({"descricao": "Ar condicionado split"})
    assert rule.applies(ctx) is True


def test_applies_false_when_no_categories_configured():
    rule = CategoryCriticalCheckRule()
    tenant = _make_tenant(categories=[])
    ctx = _make_context({"descricao": "Ar condicionado"}, tenant=tenant)
    assert rule.applies(ctx) is False


def test_applies_false_when_no_descricao():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({"descricao": ""})
    assert rule.applies(ctx) is False


def test_applies_false_when_descricao_not_in_any_category():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({"descricao": "Mesa de escritório"})
    assert rule.applies(ctx) is False


def test_applies_false_when_category_has_no_critical_checks():
    rule = CategoryCriticalCheckRule()
    no_checks_cat = CategoryConfig(
        name="other",
        display_name="OTHER",
        keywords=["mesa"],
        critical_checks=[],
    )
    tenant = _make_tenant(categories=[no_checks_cat])
    ctx = _make_context({"descricao": "Mesa grande"}, tenant=tenant)
    assert rule.applies(ctx) is False


# --- validate tests: air conditioner / BTU ---


def test_ac_missing_btu_pattern():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({
        "descricao": "Ar condicionado split",
        "complemento": "marca LG",
        "modelo": "S4000",
    })
    issues = rule.validate(ctx)
    assert len(issues) == 1
    assert issues[0].code == "CATEGORY_AR_CONDICIONADO_BTU_PATTERN_MISSING"
    assert issues[0].severity == "error"
    assert issues[0].field == "descricao"


def test_ac_btu_in_complemento():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({
        "descricao": "Ar condicionado split",
        "complemento": "9000 BTU inverter",
        "modelo": "",
    })
    issues = rule.validate(ctx)
    assert len(issues) == 0


def test_ac_btu_in_descricao():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({
        "descricao": "Ar condicionado 12000BTU",
        "complemento": "",
        "modelo": "",
    })
    issues = rule.validate(ctx)
    assert len(issues) == 0


def test_ac_btu_in_modelo():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({
        "descricao": "Split inverter",
        "complemento": "",
        "modelo": "LG 9000 btus",
    })
    issues = rule.validate(ctx)
    assert len(issues) == 0


# --- validate tests: TV / inches ---


def test_tv_missing_inches_pattern():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({
        "descricao": "Televisor Samsung",
        "complemento": "smart LED",
        "modelo": "UN43",
    })
    issues = rule.validate(ctx)
    assert len(issues) == 1
    assert issues[0].code == "CATEGORY_TV_INCHES_PATTERN_MISSING"


def test_tv_inches_in_complemento():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({
        "descricao": "TV LED",
        "complemento": '50 polegadas smart',
        "modelo": "",
    })
    issues = rule.validate(ctx)
    assert len(issues) == 0


def test_tv_inches_with_pol_abbreviation():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({
        "descricao": "TV LED",
        "complemento": "43 pol",
        "modelo": "",
    })
    issues = rule.validate(ctx)
    assert len(issues) == 0


def test_tv_inches_with_quote_mark():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({
        "descricao": "Televisão Samsung",
        "complemento": '55" smart',
        "modelo": "",
    })
    issues = rule.validate(ctx)
    assert len(issues) == 0


def test_switch_ports_pattern_in_complemento():
    rule = CategoryCriticalCheckRule()
    tenant = _make_tenant(categories=[SWITCH_CATEGORY])
    ctx = _make_context({"descricao": "Switch", "complemento": "24 portas"}, tenant=tenant)
    issues = rule.validate(ctx)
    assert issues == []


def test_dvr_channels_pattern_missing():
    rule = CategoryCriticalCheckRule()
    tenant = _make_tenant(categories=[DVR_CATEGORY])
    ctx = _make_context({"descricao": "DVR", "complemento": "gravador"}, tenant=tenant)
    issues = rule.validate(ctx)
    assert len(issues) == 1
    assert issues[0].code == "CATEGORY_DVR_CHANNELS_PATTERN_MISSING"


def test_tank_liters_pattern_in_complemento():
    rule = CategoryCriticalCheckRule()
    tenant = _make_tenant(categories=[TANK_CATEGORY])
    ctx = _make_context(
        {"descricao": "Tanque metalico", "complemento": "etanol 1500 l"},
        tenant=tenant,
    )
    issues = rule.validate(ctx)
    assert issues == []


# --- unknown critical check name is silently skipped ---


def test_unknown_critical_check_skipped():
    rule = CategoryCriticalCheckRule()
    unknown_cat = CategoryConfig(
        name="custom",
        display_name="CUSTOM",
        keywords=["custom"],
        critical_checks=["nonexistent_check"],
    )
    tenant = _make_tenant(categories=[unknown_cat])
    ctx = _make_context({"descricao": "custom item"}, tenant=tenant)
    issues = rule.validate(ctx)
    assert len(issues) == 0


# --- engine integration ---


def test_engine_integration():
    from app.core.engine import ValidationEngine

    rule = CategoryCriticalCheckRule()
    register_rule(rule)

    tenant = _make_tenant()
    engine = ValidationEngine(tenant=tenant)

    raw_rows = [
        {"Descrição": "Ar condicionado split", "Complemento": "marca LG", "Placa Anterior": ""},
        {"Descrição": "TV Samsung LED", "Complemento": "55 polegadas", "Placa Anterior": ""},
        {"Descrição": "Mesa escritório", "Complemento": "madeira", "Placa Anterior": ""},
    ]

    results = engine.validate_all(raw_rows)
    ac_issues = [i for i in results[0] if "CATEGORY" in i.code]
    assert len(ac_issues) == 1
    assert "BTU_PATTERN" in ac_issues[0].code

    tv_issues = [i for i in results[1] if "CATEGORY" in i.code]
    assert len(tv_issues) == 0

    desk_issues = [i for i in results[2] if "CATEGORY" in i.code]
    assert len(desk_issues) == 0


# --- None/missing fields handled gracefully ---


def test_none_complemento_and_modelo():
    rule = CategoryCriticalCheckRule()
    ctx = _make_context({
        "descricao": "Ar condicionado",
        "complemento": None,
        "modelo": None,
    })
    issues = rule.validate(ctx)
    assert len(issues) == 1
    assert "BTU_PATTERN" in issues[0].code


# --- required field rule ---


def test_required_fields_rule_applies_when_category_has_required_fields():
    rule = CategoryRequiredFieldsRule()
    tenant = _make_tenant(
        categories=[MONITOR_CATEGORY],
        enabled_rules=["category_required_fields"],
    )
    ctx = _make_context({"descricao": "Monitor LED"}, tenant=tenant)
    assert rule.applies(ctx) is True


def test_required_fields_rule_skips_when_category_has_no_required_fields():
    rule = CategoryRequiredFieldsRule()
    tenant = _make_tenant(
        categories=[TV_CATEGORY],
        enabled_rules=["category_required_fields"],
    )
    ctx = _make_context({"descricao": "Televisor"}, tenant=tenant)
    assert rule.applies(ctx) is False


def test_required_fields_rule_emits_missing_fields_with_help():
    rule = CategoryRequiredFieldsRule()
    tenant = _make_tenant(
        categories=[MONITOR_CATEGORY],
        enabled_rules=["category_required_fields"],
    )
    ctx = _make_context(
        {"descricao": "Monitor", "marca": "", "modelo": None, "complemento": ""},
        tenant=tenant,
    )

    issues = rule.validate(ctx)

    assert [issue.code for issue in issues] == [
        "CATEGORY_MONITOR_MARCA_REQUIRED",
        "CATEGORY_MONITOR_MODELO_REQUIRED",
        "CATEGORY_MONITOR_COMPLEMENTO_REQUIRED",
    ]
    assert issues[-1].field == "complemento"
    assert "LED 19 POL" in issues[-1].message


def test_required_fields_rule_passes_when_all_fields_present():
    rule = CategoryRequiredFieldsRule()
    tenant = _make_tenant(
        categories=[MONITOR_CATEGORY],
        enabled_rules=["category_required_fields"],
    )
    ctx = _make_context(
        {
            "descricao": "Monitor",
            "marca": "Dell",
            "modelo": "P2419H",
            "complemento": "LED 19 POL",
        },
        tenant=tenant,
    )
    assert rule.validate(ctx) == []


def test_required_fields_engine_integration():
    from app.core.engine import ValidationEngine

    register_rule(CategoryRequiredFieldsRule())
    tenant = _make_tenant(
        categories=[MONITOR_CATEGORY],
        enabled_rules=["category_required_fields"],
    )
    engine = ValidationEngine(tenant=tenant)

    raw_rows = [{"Descrição": "Monitor", "Marca": "", "Modelo": "", "Complemento": ""}]
    results = engine.validate_all(raw_rows)

    assert len(results[0]) == 3
    assert results[0][0].severity == "warning"
