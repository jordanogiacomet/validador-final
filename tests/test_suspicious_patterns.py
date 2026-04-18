from app.core.context import ValidationContext
from app.core.engine import ValidationEngine
from app.core.registry import RULE_REGISTRY, register_rule
from app.core.tenant_config import SuspiciousPatternsConfig, TenantConfig
from app.rules.suspicious_patterns import SuspiciousPatternRule


def setup_function() -> None:
    RULE_REGISTRY.clear()


def teardown_function() -> None:
    RULE_REGISTRY.clear()


def _tenant(
    suspicious_patterns: SuspiciousPatternsConfig | None = None,
) -> TenantConfig:
    return TenantConfig(
        tenant_id="empresa_exemplo",
        display_name="Empresa Exemplo",
        enabled_rules=["suspicious_pattern"],
        suspicious_patterns=suspicious_patterns or SuspiciousPatternsConfig(),
    )


def _context(
    *,
    descricao: str = "",
    complemento: str = "",
    suspicious_patterns: SuspiciousPatternsConfig | None = None,
) -> ValidationContext:
    return ValidationContext(
        tenant=_tenant(suspicious_patterns),
        row_index=0,
        normalized_row={
            "descricao": descricao,
            "complemento": complemento,
        },
        shared_context={},
    )


def test_suspicious_pattern_rule_is_opt_in_when_no_patterns_are_configured() -> None:
    rule = SuspiciousPatternRule()

    assert rule.applies(_context()) is False
    assert rule.validate(_context(descricao="Descricao limpa")) == []


def test_suspicious_pattern_rule_warns_on_literal_match_in_descricao() -> None:
    rule = SuspiciousPatternRule()
    context = _context(
        descricao="Material NAO INFORMADO",
        suspicious_patterns=SuspiciousPatternsConfig(
            literal_patterns=["não informado"],
        ),
    )

    issues = rule.validate(context)

    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "SUSPICIOUS_PATTERN_DETECTED"
    assert issue.severity == "warning"
    assert issue.field == "descricao"
    assert "literal" in issue.message
    assert "não informado" in issue.message


def test_suspicious_pattern_rule_warns_on_regex_match_in_complemento() -> None:
    rule = SuspiciousPatternRule()
    context = _context(
        complemento="Patrimonio em TESTE 123",
        suspicious_patterns=SuspiciousPatternsConfig(
            regex_patterns=[r"\bteste\s+\d+\b"],
        ),
    )

    issues = rule.validate(context)

    assert len(issues) == 1
    issue = issues[0]
    assert issue.code == "SUSPICIOUS_PATTERN_DETECTED"
    assert issue.severity == "warning"
    assert issue.field == "complemento"
    assert "regex" in issue.message
    assert r"\bteste\s+\d+\b" in issue.message


def test_suspicious_pattern_rule_checks_descricao_and_complemento_independently() -> None:
    rule = SuspiciousPatternRule()
    context = _context(
        descricao="Descricao diversos",
        complemento="complemento teste 321",
        suspicious_patterns=SuspiciousPatternsConfig(
            literal_patterns=["diversos"],
            regex_patterns=[r"\bteste\s+\d+\b"],
        ),
    )

    issues = rule.validate(context)

    assert [issue.field for issue in issues] == ["descricao", "complemento"]


def test_engine_applies_suspicious_pattern_rule_when_enabled() -> None:
    register_rule(SuspiciousPatternRule())
    engine = ValidationEngine(
        _tenant(
            SuspiciousPatternsConfig(
                literal_patterns=["diversos"],
            )
        )
    )

    results = engine.validate_all(
        [
            {
                "Item": "001",
                "Placa Anterior": "",
                "Descrição": "BEM DIVERSOS",
                "Complemento": "",
            }
        ]
    )

    assert len(results[0]) == 1
    issue = results[0][0]
    assert issue.code == "SUSPICIOUS_PATTERN_DETECTED"
    assert issue.field == "descricao"
