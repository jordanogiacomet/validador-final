from app.core.context import ValidationContext
from app.core.registry import RULE_REGISTRY, register_rule
from app.core.tenant_config import TenantConfig
from app.rules.zero_item_quality import ZeroItemQualityRule


def make_tenant(**overrides):
    defaults = {
        "tenant_id": "test",
        "display_name": "Test",
        "enabled_rules": ["zero_item_quality"],
        "thresholds": {"short_complement_max_words": 3},
    }
    defaults.update(overrides)
    return TenantConfig(**defaults)


def make_context(row, tenant=None, all_rows=None, shared_context=None):
    return ValidationContext(
        tenant=tenant or make_tenant(),
        row_index=0,
        normalized_row=row,
        all_rows=all_rows or [row],
        shared_context=shared_context if shared_context is not None else {},
    )


def setup_function():
    RULE_REGISTRY.clear()


def teardown_function():
    RULE_REGISTRY.clear()


rule = ZeroItemQualityRule()


class TestApplies:
    def test_applies_to_zero_items(self):
        ctx = make_context({"flag_item_cadastrado_do_zero": 1})
        assert rule.applies(ctx) is True

    def test_does_not_apply_to_collected_items(self):
        ctx = make_context({"flag_item_cadastrado_do_zero": 0, "flag_item_coletado": 1})
        assert rule.applies(ctx) is False

    def test_does_not_apply_when_flag_missing(self):
        ctx = make_context({})
        assert rule.applies(ctx) is False


class TestComplementoEmpty:
    def test_warns_when_complemento_empty(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": None,
            "marca": "Samsung",
            "modelo": "X100",
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_EMPTY" in codes

    def test_warns_when_complemento_blank_string(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": "   ",
            "marca": "Samsung",
            "modelo": "X100",
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_EMPTY" in codes


class TestComplementoShort:
    def test_warns_when_complemento_too_short(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": "cor branca",
            "marca": "Samsung",
            "modelo": "X100",
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_SHORT" in codes

    def test_no_warning_when_complemento_long_enough(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": "cor branca com detalhes em preto",
            "marca": "Samsung",
            "modelo": "X100",
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_SHORT" not in codes

    def test_respects_configurable_threshold(self):
        tenant = make_tenant(thresholds={"short_complement_max_words": 5})
        ctx = make_context(
            {
                "flag_item_cadastrado_do_zero": 1,
                "complemento": "cor branca grande",
                "marca": "Samsung",
                "modelo": "X100",
            },
            tenant=tenant,
        )
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_SHORT" in codes


class TestMarcaMissing:
    def test_warns_when_marca_missing(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": "cor branca com detalhes em preto",
            "marca": None,
            "modelo": "X100",
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_MARCA_MISSING" in codes

    def test_warns_when_marca_blank(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": "cor branca com detalhes em preto",
            "marca": "  ",
            "modelo": "X100",
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_MARCA_MISSING" in codes

    def test_no_warning_when_marca_present(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": "cor branca com detalhes em preto",
            "marca": "LG",
            "modelo": "X100",
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_MARCA_MISSING" not in codes


class TestModeloMissing:
    def test_warns_when_modelo_missing(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": "cor branca com detalhes em preto",
            "marca": "LG",
            "modelo": None,
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_MODELO_MISSING" in codes

    def test_no_warning_when_modelo_present(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": "cor branca com detalhes em preto",
            "marca": "LG",
            "modelo": "ABC-123",
        })
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_MODELO_MISSING" not in codes


class TestRelativeComplementQuality:
    def _make_peer_rows(self):
        return [
            {
                "flag_item_cadastrado_do_zero": 1,
                "descricao": "Mesa",
                "complemento": "mesa de escritório grande com gavetas laterais amplas",
                "marca": "X",
                "modelo": "Y",
            },
            {
                "flag_item_cadastrado_do_zero": 1,
                "descricao": "Mesa",
                "complemento": "mesa de escritório média com acabamento em madeira",
                "marca": "X",
                "modelo": "Y",
            },
            {
                "flag_item_cadastrado_do_zero": 1,
                "descricao": "Mesa",
                "complemento": "mesa",
                "marca": "X",
                "modelo": "Y",
            },
        ]

    def test_warns_below_peer_average(self):
        rows = self._make_peer_rows()
        shared = {}
        ctx = make_context(rows[2], all_rows=rows, shared_context=shared)
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_BELOW_PEERS" in codes

    def test_no_warning_at_peer_average(self):
        rows = self._make_peer_rows()
        shared = {}
        ctx = make_context(rows[0], all_rows=rows, shared_context=shared)
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_BELOW_PEERS" not in codes

    def test_no_comparison_without_peers(self):
        row = {
            "flag_item_cadastrado_do_zero": 1,
            "descricao": "Cadeira",
            "complemento": "c",
            "marca": "X",
            "modelo": "Y",
        }
        shared = {}
        ctx = make_context(row, all_rows=[row], shared_context=shared)
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_BELOW_PEERS" not in codes

    def test_no_comparison_without_descricao(self):
        row = {
            "flag_item_cadastrado_do_zero": 1,
            "descricao": None,
            "complemento": "c",
            "marca": "X",
            "modelo": "Y",
        }
        ctx = make_context(row)
        issues = rule.validate(ctx)
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_BELOW_PEERS" not in codes

    def test_caches_stats_in_shared_context(self):
        rows = self._make_peer_rows()
        shared = {}
        ctx1 = make_context(rows[0], all_rows=rows, shared_context=shared)
        rule.validate(ctx1)
        assert "_zero_item_complement_stats" in ctx1.shared_context

        ctx2 = make_context(
            rows[1], all_rows=rows, shared_context=ctx1.shared_context
        )
        rule.validate(ctx2)
        assert "_zero_item_complement_stats" in ctx2.shared_context


class TestCleanItem:
    def test_no_issues_for_perfect_zero_item(self):
        ctx = make_context({
            "flag_item_cadastrado_do_zero": 1,
            "complemento": "equipamento de ar condicionado split inverter 12000 BTU",
            "marca": "Samsung",
            "modelo": "AR12TSHZ",
        })
        issues = rule.validate(ctx)
        assert len(issues) == 0


class TestEngineIntegration:
    def test_rule_works_via_engine(self):
        from app.core.engine import ValidationEngine

        register_rule(ZeroItemQualityRule())
        tenant = make_tenant()
        engine = ValidationEngine(tenant=tenant)
        raw_rows = [
            {"Item": "001", "Complemento": None, "Marca": None, "Modelo": None},
        ]
        results = engine.validate_all(raw_rows)
        issues = results[0]
        codes = [i.code for i in issues]
        assert "ZERO_ITEM_COMPLEMENTO_EMPTY" in codes
        assert "ZERO_ITEM_MARCA_MISSING" in codes
        assert "ZERO_ITEM_MODELO_MISSING" in codes
