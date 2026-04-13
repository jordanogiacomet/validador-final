from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Protocol

from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.core.tenant_config import LLMConfig
from app.rules.base import BaseRule

logger = logging.getLogger(__name__)

TENANTS_DIR = Path(__file__).resolve().parent.parent / "tenants"

VALID_SEVERITIES = {"warning", "error"}


class LLMClient(Protocol):
    def complete(self, model: str, prompt: str, temperature: float, max_tokens: int) -> str: ...


class AnthropicLLMClient:
    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.Anthropic()

    def complete(self, model: str, prompt: str, temperature: float, max_tokens: int) -> str:
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text


_default_client: LLMClient | None = None


def get_default_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = AnthropicLLMClient()
    return _default_client


def set_default_client(client: LLMClient | None) -> None:
    global _default_client
    _default_client = client


def load_prompt_template(tenant_id: str, prompt_file: str) -> str:
    prompt_path = TENANTS_DIR / tenant_id / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def format_prompt(template: str, row: dict[str, Any]) -> str:
    return template.format(
        descricao=row.get("descricao") or "",
        marca=row.get("marca") or "",
        modelo=row.get("modelo") or "",
        ns=row.get("ns") or "",
        complemento=row.get("complemento") or "",
        observacao=row.get("observacao") or "",
    )


def parse_llm_response(response_text: str) -> list[dict[str, str]]:
    json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
    if not json_match:
        return []
    try:
        findings = json.loads(json_match.group())
    except json.JSONDecodeError:
        return []
    if not isinstance(findings, list):
        return []
    valid: list[dict[str, str]] = []
    for f in findings:
        if isinstance(f, dict) and "issue" in f:
            valid.append({
                "issue": str(f["issue"]),
                "severity": str(f.get("severity", "warning"))
                if f.get("severity") in VALID_SEVERITIES
                else "warning",
                "field": str(f["field"]) if f.get("field") else None,
            })
    return valid


def normalize_findings(findings: list[dict[str, str]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for i, f in enumerate(findings):
        issues.append(
            ValidationIssue(
                code=f"LLM_AUDIT_FINDING_{i + 1}",
                severity=f.get("severity", "warning"),
                message=f"Auditoria LLM: {f['issue']}",
                field=f.get("field"),
            )
        )
    return issues


class LLMAuditRule(BaseRule):
    name: str = "llm_audit"

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client

    def _get_client(self) -> LLMClient:
        if self._client is not None:
            return self._client
        return get_default_client()

    def applies(self, context: ValidationContext) -> bool:
        if not context.tenant.llm.enabled:
            return False
        return context.normalized_row.get("flag_item_cadastrado_do_zero") == 1

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        llm_config: LLMConfig = context.tenant.llm

        try:
            template = load_prompt_template(context.tenant.tenant_id, llm_config.prompt_file)
        except FileNotFoundError:
            return [
                ValidationIssue(
                    code="LLM_AUDIT_PROMPT_NOT_FOUND",
                    severity="warning",
                    message=f"Arquivo de prompt não encontrado: {llm_config.prompt_file}",
                    field=None,
                )
            ]

        prompt = format_prompt(template, context.normalized_row)

        try:
            response_text = self._get_client().complete(
                model=llm_config.model,
                prompt=prompt,
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
            )
        except Exception as exc:
            logger.warning("LLM audit failed for row %d: %s", context.row_index, exc)
            return [
                ValidationIssue(
                    code="LLM_AUDIT_FAILURE",
                    severity="warning",
                    message=f"Auditoria LLM falhou: {type(exc).__name__}",
                    field=None,
                )
            ]

        findings = parse_llm_response(response_text)
        return normalize_findings(findings)
