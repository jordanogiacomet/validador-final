from __future__ import annotations

from app.core.context import ValidationContext
from app.core.llm_cache import LLM_FORCE_REFRESH_PARAM, FileLLMResponseCache
from app.core.registry import RULE_REGISTRY, register_rule
from app.core.tenant_config import LLMConfig, TenantConfig
from app.rules.llm_audit import (
    DEFAULT_PROMPT_VERSION,
    LLM_AUDIT_METADATA_KEY,
    LLMAuditRule,
    format_prompt,
    normalize_findings,
    parse_llm_response,
    parse_prompt_template,
)


def setup_function():
    RULE_REGISTRY.clear()


def teardown_function():
    RULE_REGISTRY.clear()


def _tenant(
    llm_enabled: bool = True,
    prompt_file: str = "prompts/audit.txt",
    cache_ttl_seconds: int = 0,
) -> TenantConfig:
    return TenantConfig(
        tenant_id="empresa_exemplo",
        display_name="Empresa Exemplo",
        enabled_rules=["llm_audit"],
        llm=LLMConfig(
            enabled=llm_enabled,
            model="claude-sonnet-4-20250514",
            temperature=0.0,
            max_tokens=1024,
            prompt_file=prompt_file,
            cache_ttl_seconds=cache_ttl_seconds,
        ),
    )


def _ctx(
    tenant: TenantConfig | None = None,
    row: dict | None = None,
    flag_zero: int = 1,
    shared_context: dict | None = None,
) -> ValidationContext:
    if tenant is None:
        tenant = _tenant()
    if row is None:
        row = {
            "item": "001",
            "placa_anterior": "",
            "descricao": "Mesa de escritório",
            "marca": "",
            "modelo": "",
            "ns": "",
            "complemento": "",
            "observacao": "",
            "flag_item_coletado": 0,
            "flag_item_cadastrado_do_zero": flag_zero,
        }
    return ValidationContext(
        tenant=tenant,
        row_index=0,
        normalized_row=row,
        shared_context=shared_context or {},
    )


class FakeLLMClient:
    def __init__(self, response: str = "[]", error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def complete(self, model: str, prompt: str, temperature: float, max_tokens: int) -> str:
        self.calls.append({
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        if self.error:
            raise self.error
        return self.response


# --- applies tests ---


def test_applies_when_llm_enabled_and_zero_item():
    rule = LLMAuditRule()
    ctx = _ctx(flag_zero=1)
    assert rule.applies(ctx) is True


def test_not_applies_when_llm_disabled():
    rule = LLMAuditRule()
    ctx = _ctx(tenant=_tenant(llm_enabled=False))
    assert rule.applies(ctx) is False


def test_not_applies_when_collected_item():
    rule = LLMAuditRule()
    ctx = _ctx(flag_zero=0)
    assert rule.applies(ctx) is False


# --- parse_llm_response tests ---


def test_parse_valid_json_array():
    resp = '[{"issue": "Descrição vaga", "severity": "warning", "field": "descricao"}]'
    findings = parse_llm_response(resp)
    assert len(findings) == 1
    assert findings[0]["issue"] == "Descrição vaga"
    assert findings[0]["severity"] == "warning"
    assert findings[0]["field"] == "descricao"


def test_parse_empty_array():
    assert parse_llm_response("[]") == []


def test_parse_json_with_surrounding_text():
    resp = (
        'Here are the findings:\n'
        '[{"issue": "test", "severity": "error", "field": "marca"}]\nDone.'
    )
    findings = parse_llm_response(resp)
    assert len(findings) == 1
    assert findings[0]["severity"] == "error"


def test_parse_invalid_json():
    assert parse_llm_response("not json at all") == []


def test_parse_invalid_severity_defaults_to_warning():
    resp = '[{"issue": "test", "severity": "critical", "field": "marca"}]'
    findings = parse_llm_response(resp)
    assert findings[0]["severity"] == "warning"


def test_parse_missing_field_key():
    resp = '[{"issue": "test"}]'
    findings = parse_llm_response(resp)
    assert len(findings) == 1
    assert findings[0]["field"] is None


def test_parse_prompt_template_reads_frontmatter_version():
    loaded = parse_prompt_template("---\nversion: v2\n---\nDesc: {descricao}")

    assert loaded.version == "v2"
    assert loaded.template == "Desc: {descricao}"


def test_parse_prompt_template_defaults_legacy_without_frontmatter():
    loaded = parse_prompt_template("Desc: {descricao}")

    assert loaded.version == DEFAULT_PROMPT_VERSION
    assert loaded.template == "Desc: {descricao}"


# --- normalize_findings tests ---


def test_normalize_findings_creates_issues():
    findings = [
        {"issue": "Problema 1", "severity": "warning", "field": "descricao"},
        {"issue": "Problema 2", "severity": "error", "field": "marca"},
    ]
    issues = normalize_findings(
        findings,
        model="claude-sonnet-4-20250514",
        prompt_version="v1",
    )
    assert len(issues) == 2
    assert issues[0].code == "LLM_AUDIT_FINDING_1"
    assert issues[0].severity == "warning"
    assert "Problema 1" in issues[0].message
    assert issues[0].meta == {
        "model": "claude-sonnet-4-20250514",
        "prompt_version": "v1",
    }
    assert issues[1].code == "LLM_AUDIT_FINDING_2"
    assert issues[1].severity == "error"


def test_normalize_empty_findings():
    assert normalize_findings([], model="claude", prompt_version="v1") == []


# --- format_prompt tests ---


def test_format_prompt_fills_fields():
    template = "Desc: {descricao}, Marca: {marca}"
    row = {"descricao": "Mesa", "marca": "Acme"}
    result = format_prompt(template, row)
    assert result == "Desc: Mesa, Marca: Acme"


def test_format_prompt_none_values_become_empty():
    template = "Desc: {descricao}, Marca: {marca}"
    row = {"descricao": None, "marca": None}
    result = format_prompt(template, row)
    assert result == "Desc: , Marca: "


# --- validate tests with fake client ---


def test_validate_returns_findings():
    response = '[{"issue": "Descrição genérica", "severity": "warning", "field": "descricao"}]'
    client = FakeLLMClient(response=response)
    rule = LLMAuditRule(client=client)
    ctx = _ctx()
    issues = rule.validate(ctx)
    assert len(issues) == 1
    assert issues[0].code == "LLM_AUDIT_FINDING_1"
    assert "Descrição genérica" in issues[0].message
    assert issues[0].meta == {
        "model": "claude-sonnet-4-20250514",
        "prompt_version": "empresa_exemplo-v1",
    }
    assert ctx.shared_context[LLM_AUDIT_METADATA_KEY] == {
        "models": ["claude-sonnet-4-20250514"],
        "prompt_versions": ["empresa_exemplo-v1"],
    }
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "claude-sonnet-4-20250514"


def test_validate_empty_response():
    client = FakeLLMClient(response="[]")
    rule = LLMAuditRule(client=client)
    ctx = _ctx()
    issues = rule.validate(ctx)
    assert issues == []
    assert ctx.shared_context[LLM_AUDIT_METADATA_KEY]["prompt_versions"] == [
        "empresa_exemplo-v1"
    ]


def test_validate_llm_failure_returns_warning():
    client = FakeLLMClient(error=TimeoutError("connection timed out"))
    rule = LLMAuditRule(client=client)
    ctx = _ctx()
    issues = rule.validate(ctx)
    assert len(issues) == 1
    assert issues[0].code == "LLM_AUDIT_FAILURE"
    assert issues[0].severity == "warning"
    assert "TimeoutError" in issues[0].message
    assert issues[0].meta == {
        "model": "claude-sonnet-4-20250514",
        "prompt_version": "empresa_exemplo-v1",
    }


def test_validate_generic_exception_returns_warning():
    client = FakeLLMClient(error=RuntimeError("API error"))
    rule = LLMAuditRule(client=client)
    ctx = _ctx()
    issues = rule.validate(ctx)
    assert len(issues) == 1
    assert issues[0].code == "LLM_AUDIT_FAILURE"
    assert issues[0].severity == "warning"


def test_validate_prompt_not_found():
    client = FakeLLMClient()
    rule = LLMAuditRule(client=client)
    ctx = _ctx(tenant=_tenant(prompt_file="nonexistent/prompt.txt"))
    issues = rule.validate(ctx)
    assert len(issues) == 1
    assert issues[0].code == "LLM_AUDIT_PROMPT_NOT_FOUND"
    assert issues[0].severity == "warning"
    assert issues[0].meta == {
        "model": "claude-sonnet-4-20250514",
        "prompt_version": "unknown",
    }


def test_validate_passes_correct_params_to_client():
    client = FakeLLMClient(response="[]")
    rule = LLMAuditRule(client=client)
    ctx = _ctx()
    rule.validate(ctx)
    call = client.calls[0]
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == 1024


def test_validate_caches_successful_response_and_reuses_it(tmp_path):
    now = 1000.0
    cache_path = tmp_path / "llm_cache.json"
    cache = FileLLMResponseCache(cache_path, clock=lambda: now)
    response = (
        '[{"issue": "Complemento genérico", "severity": "warning", '
        '"field": "complemento"}]'
    )
    client = FakeLLMClient(response=response)
    rule = LLMAuditRule(client=client, cache=cache)
    tenant = _tenant(cache_ttl_seconds=60)

    first_issues = rule.validate(_ctx(tenant=tenant))
    second_client = FakeLLMClient(
        response='[{"issue": "Não deveria chamar", "field": "descricao"}]'
    )
    second_rule = LLMAuditRule(
        client=second_client,
        cache=FileLLMResponseCache(cache_path, clock=lambda: now),
    )
    second_issues = second_rule.validate(_ctx(tenant=tenant))

    assert len(client.calls) == 1
    assert second_client.calls == []
    assert first_issues[0].message == second_issues[0].message
    assert "Complemento genérico" in second_issues[0].message


def test_validate_ttl_expired_cache_calls_llm_again(tmp_path):
    now = 1000.0
    cache = FileLLMResponseCache(tmp_path / "llm_cache.json", clock=lambda: now)
    client = FakeLLMClient(
        response='[{"issue": "Primeira resposta", "field": "descricao"}]'
    )
    rule = LLMAuditRule(client=client, cache=cache)
    tenant = _tenant(cache_ttl_seconds=60)

    first_issues = rule.validate(_ctx(tenant=tenant))
    assert "Primeira resposta" in first_issues[0].message

    now = 1100.0
    client.response = '[{"issue": "Resposta atualizada", "field": "descricao"}]'
    second_issues = rule.validate(_ctx(tenant=tenant))

    assert len(client.calls) == 2
    assert "Resposta atualizada" in second_issues[0].message


def test_validate_force_refresh_bypasses_and_refreshes_cache(tmp_path):
    now = 1000.0
    cache = FileLLMResponseCache(tmp_path / "llm_cache.json", clock=lambda: now)
    client = FakeLLMClient(
        response='[{"issue": "Resposta cacheada", "field": "descricao"}]'
    )
    rule = LLMAuditRule(client=client, cache=cache)
    tenant = _tenant(cache_ttl_seconds=60)

    cached_issues = rule.validate(_ctx(tenant=tenant))
    assert "Resposta cacheada" in cached_issues[0].message

    client.response = '[{"issue": "Resposta forçada", "field": "descricao"}]'
    refreshed_issues = rule.validate(
        _ctx(
            tenant=tenant,
            shared_context={LLM_FORCE_REFRESH_PARAM: True},
        )
    )

    client.response = '[{"issue": "Resposta que não deve ser chamada", "field": "descricao"}]'
    reused_issues = rule.validate(_ctx(tenant=tenant))

    assert len(client.calls) == 2
    assert "Resposta forçada" in refreshed_issues[0].message
    assert "Resposta forçada" in reused_issues[0].message


# --- engine integration ---


def test_engine_integration():
    from app.core.engine import ValidationEngine

    response = '[{"issue": "Teste", "severity": "warning", "field": "descricao"}]'
    client = FakeLLMClient(response=response)
    rule = LLMAuditRule(client=client)
    register_rule(rule)

    tenant = _tenant()
    engine = ValidationEngine(tenant=tenant)
    raw_rows = [{"Placa Anterior": "", "Item": "001", "Descrição": "Mesa"}]
    results = engine.validate_all(raw_rows)
    llm_findings = [
        i for issues in results.values() for i in issues if i.code.startswith("LLM_AUDIT_FINDING")
    ]
    assert len(llm_findings) > 0


def test_engine_skips_collected_items():
    from app.core.engine import ValidationEngine

    client = FakeLLMClient(response='[{"issue": "X", "severity": "warning", "field": "a"}]')
    rule = LLMAuditRule(client=client)
    register_rule(rule)

    tenant = _tenant()
    engine = ValidationEngine(tenant=tenant)
    raw_rows = [{"Placa Anterior": "ABC123", "Item": "001", "Descrição": "Mesa"}]
    results = engine.validate_all(raw_rows)
    llm_issues = [
        issue
        for issues in results.values()
        for issue in issues
        if issue.code.startswith("LLM_AUDIT")
    ]
    assert llm_issues == []
    assert len(client.calls) == 0
