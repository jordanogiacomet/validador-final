from __future__ import annotations

import json
import logging
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.core.llm_cache import (
    LLM_FORCE_REFRESH_PARAM,
    FileLLMResponseCache,
    LLMResponseCache,
    build_llm_cache_key,
    normalize_llm_cache_payload,
    resolve_force_refresh,
)
from app.core.metrics import record_llm_cache_lookup, record_llm_request
from app.core.tenant_config import LLMConfig
from app.rules.base import BaseRule

logger = logging.getLogger(__name__)

TENANTS_DIR = Path(__file__).resolve().parent.parent / "tenants"

VALID_SEVERITIES = {"warning", "error"}
DEFAULT_LLM_PROVIDER_HOST = "api.anthropic.com"
DEFAULT_LLM_PROVIDER_PORT = 443
DEFAULT_PROMPT_VERSION = "legacy"
UNKNOWN_PROMPT_VERSION = "unknown"
LLM_AUDIT_METADATA_KEY = "llm_audit_metadata"
_PROMPT_FRONTMATTER_RE = re.compile(
    r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z",
    re.DOTALL,
)


@dataclass(frozen=True)
class LoadedPromptTemplate:
    version: str
    template: str


@dataclass(frozen=True)
class LLMAttemptFailure:
    model: str
    error: Exception


@dataclass(frozen=True)
class LLMCompletionResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    def complete(
        self,
        model: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str | LLMCompletionResult: ...


class AnthropicLLMClient:
    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.Anthropic()

    def complete(
        self,
        model: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMCompletionResult:
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        content = "".join(
            str(getattr(block, "text", ""))
            for block in getattr(response, "content", [])
            if getattr(block, "text", None)
        )
        usage = getattr(response, "usage", None)
        return LLMCompletionResult(
            text=content,
            input_tokens=_coerce_non_negative_int(getattr(usage, "input_tokens", 0)),
            output_tokens=_coerce_non_negative_int(
                getattr(usage, "output_tokens", 0)
            ),
        )


_default_client: LLMClient | None = None


def get_default_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = AnthropicLLMClient()
    return _default_client


def set_default_client(client: LLMClient | None) -> None:
    global _default_client
    _default_client = client


def get_llm_provider_target(model: str) -> tuple[str, int]:
    del model
    return DEFAULT_LLM_PROVIDER_HOST, DEFAULT_LLM_PROVIDER_PORT


def probe_llm_provider(model: str, timeout_ms: int = 500) -> str:
    host, port = get_llm_provider_target(model)
    timeout_seconds = max(timeout_ms, 1) / 1000.0
    with socket.create_connection((host, port), timeout=timeout_seconds):
        return f"{host}:{port}"


def parse_prompt_template(content: str) -> LoadedPromptTemplate:
    match = _PROMPT_FRONTMATTER_RE.match(content)
    if not match:
        return LoadedPromptTemplate(
            version=DEFAULT_PROMPT_VERSION,
            template=content,
        )

    raw_frontmatter, template = match.groups()
    parsed_frontmatter = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(parsed_frontmatter, dict):
        parsed_frontmatter = {}

    version = parsed_frontmatter.get("version") or DEFAULT_PROMPT_VERSION
    return LoadedPromptTemplate(
        version=str(version),
        template=template.lstrip("\r\n"),
    )


def load_prompt_template(tenant_id: str, prompt_file: str) -> LoadedPromptTemplate:
    prompt_path = TENANTS_DIR / tenant_id / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return parse_prompt_template(prompt_path.read_text(encoding="utf-8"))


def format_prompt(template: str, row: dict[str, Any]) -> str:
    return template.format(
        descricao=row.get("descricao") or "",
        marca=row.get("marca") or "",
        modelo=row.get("modelo") or "",
        ns=row.get("ns") or "",
        complemento=row.get("complemento") or "",
        observacao=row.get("observacao") or "",
    )


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def normalize_completion_result(
    result: str | LLMCompletionResult,
) -> LLMCompletionResult:
    if isinstance(result, LLMCompletionResult):
        return result
    return LLMCompletionResult(text=str(result))


def build_llm_issue_meta(
    *,
    model: str,
    prompt_version: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": prompt_version,
    }


def build_llm_failure_meta(
    *,
    model: str,
    prompt_version: str,
    failures: list[LLMAttemptFailure],
) -> dict[str, Any]:
    meta = build_llm_issue_meta(
        model=model,
        prompt_version=prompt_version,
    )
    attempted_models = [failure.model for failure in failures]
    meta["attempted_models"] = attempted_models
    meta["primary_failure"] = describe_llm_error(failures[0].error)
    meta["final_failure"] = describe_llm_error(failures[-1].error)
    return meta


def _build_empty_llm_usage() -> dict[str, Any]:
    return {
        "audited_rows": 0,
        "provider_requests": 0,
        "cache_hits": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "findings": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "models": {},
    }


def _build_empty_model_usage() -> dict[str, int]:
    return {
        "provider_requests": 0,
        "cache_hits": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "findings": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def _ensure_llm_usage_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    usage = metadata.setdefault("usage", _build_empty_llm_usage())
    if not isinstance(usage, dict):
        usage = _build_empty_llm_usage()
        metadata["usage"] = usage

    for field in (
        "audited_rows",
        "provider_requests",
        "cache_hits",
        "successful_requests",
        "failed_requests",
        "findings",
        "input_tokens",
        "output_tokens",
    ):
        usage[field] = _coerce_non_negative_int(usage.get(field, 0))

    models = usage.setdefault("models", {})
    if not isinstance(models, dict):
        usage["models"] = {}
    return usage


def _ensure_model_usage(usage: dict[str, Any], model: str) -> dict[str, int]:
    models = usage.setdefault("models", {})
    raw_stats = models.get(model)
    if not isinstance(raw_stats, dict):
        raw_stats = _build_empty_model_usage()
        models[model] = raw_stats

    for field in (
        "provider_requests",
        "cache_hits",
        "successful_requests",
        "failed_requests",
        "findings",
        "input_tokens",
        "output_tokens",
    ):
        raw_stats[field] = _coerce_non_negative_int(raw_stats.get(field, 0))
    return raw_stats


def _increment_counter(payload: dict[str, Any], field: str, amount: int = 1) -> None:
    payload[field] = _coerce_non_negative_int(payload.get(field, 0)) + max(amount, 0)


def _ensure_llm_audit_metadata(shared_context: dict) -> dict[str, Any]:
    metadata = shared_context.setdefault(LLM_AUDIT_METADATA_KEY, {})
    if not isinstance(metadata, dict):
        metadata = {}
        shared_context[LLM_AUDIT_METADATA_KEY] = metadata

    models = metadata.setdefault("models", [])
    if not isinstance(models, list):
        metadata["models"] = []
    prompt_versions = metadata.setdefault("prompt_versions", [])
    if not isinstance(prompt_versions, list):
        metadata["prompt_versions"] = []
    _ensure_llm_usage_metadata(metadata)
    return metadata


def record_llm_audit_metadata(
    shared_context: dict,
    *,
    model: str,
    prompt_version: str,
) -> None:
    metadata = _ensure_llm_audit_metadata(shared_context)
    models = metadata.setdefault("models", [])
    prompt_versions = metadata.setdefault("prompt_versions", [])

    if model and model not in models:
        models.append(model)
    if prompt_version and prompt_version not in prompt_versions:
        prompt_versions.append(prompt_version)


def record_llm_audit_row(shared_context: dict) -> None:
    metadata = _ensure_llm_audit_metadata(shared_context)
    usage = _ensure_llm_usage_metadata(metadata)
    _increment_counter(usage, "audited_rows")


def record_llm_audit_cache_hit(shared_context: dict, *, model: str) -> None:
    metadata = _ensure_llm_audit_metadata(shared_context)
    usage = _ensure_llm_usage_metadata(metadata)
    _increment_counter(usage, "cache_hits")

    model_usage = _ensure_model_usage(usage, model)
    _increment_counter(model_usage, "cache_hits")


def record_llm_audit_request(
    shared_context: dict,
    *,
    model: str,
    outcome: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    metadata = _ensure_llm_audit_metadata(shared_context)
    usage = _ensure_llm_usage_metadata(metadata)
    model_usage = _ensure_model_usage(usage, model)

    _increment_counter(usage, "provider_requests")
    _increment_counter(model_usage, "provider_requests")

    if outcome == "success":
        _increment_counter(usage, "successful_requests")
        _increment_counter(model_usage, "successful_requests")
    else:
        _increment_counter(usage, "failed_requests")
        _increment_counter(model_usage, "failed_requests")

    normalized_input_tokens = _coerce_non_negative_int(input_tokens)
    normalized_output_tokens = _coerce_non_negative_int(output_tokens)
    _increment_counter(usage, "input_tokens", normalized_input_tokens)
    _increment_counter(usage, "output_tokens", normalized_output_tokens)
    _increment_counter(model_usage, "input_tokens", normalized_input_tokens)
    _increment_counter(model_usage, "output_tokens", normalized_output_tokens)


def record_llm_findings(
    shared_context: dict,
    *,
    model: str,
    findings_count: int,
) -> None:
    normalized_findings_count = _coerce_non_negative_int(findings_count)
    if normalized_findings_count <= 0:
        return

    metadata = _ensure_llm_audit_metadata(shared_context)
    usage = _ensure_llm_usage_metadata(metadata)
    model_usage = _ensure_model_usage(usage, model)
    _increment_counter(usage, "findings", normalized_findings_count)
    _increment_counter(model_usage, "findings", normalized_findings_count)


def snapshot_llm_audit_metadata(shared_context: dict) -> dict[str, Any] | None:
    metadata = shared_context.get(LLM_AUDIT_METADATA_KEY)
    if not isinstance(metadata, dict):
        return None

    snapshot: dict[str, Any] = {
        "models": [
            str(model).strip()
            for model in metadata.get("models", [])
            if str(model).strip()
        ],
        "prompt_versions": [
            str(prompt_version).strip()
            for prompt_version in metadata.get("prompt_versions", [])
            if str(prompt_version).strip()
        ],
    }

    usage = metadata.get("usage")
    if isinstance(usage, dict):
        usage_snapshot = {
            "audited_rows": _coerce_non_negative_int(usage.get("audited_rows", 0)),
            "provider_requests": _coerce_non_negative_int(
                usage.get("provider_requests", 0)
            ),
            "cache_hits": _coerce_non_negative_int(usage.get("cache_hits", 0)),
            "successful_requests": _coerce_non_negative_int(
                usage.get("successful_requests", 0)
            ),
            "failed_requests": _coerce_non_negative_int(
                usage.get("failed_requests", 0)
            ),
            "findings": _coerce_non_negative_int(usage.get("findings", 0)),
            "input_tokens": _coerce_non_negative_int(usage.get("input_tokens", 0)),
            "output_tokens": _coerce_non_negative_int(usage.get("output_tokens", 0)),
            "models": {},
        }
        raw_models = usage.get("models", {})
        if isinstance(raw_models, dict):
            for raw_model, raw_stats in raw_models.items():
                model = str(raw_model).strip()
                if not model or not isinstance(raw_stats, dict):
                    continue
                usage_snapshot["models"][model] = {
                    "provider_requests": _coerce_non_negative_int(
                        raw_stats.get("provider_requests", 0)
                    ),
                    "cache_hits": _coerce_non_negative_int(
                        raw_stats.get("cache_hits", 0)
                    ),
                    "successful_requests": _coerce_non_negative_int(
                        raw_stats.get("successful_requests", 0)
                    ),
                    "failed_requests": _coerce_non_negative_int(
                        raw_stats.get("failed_requests", 0)
                    ),
                    "findings": _coerce_non_negative_int(raw_stats.get("findings", 0)),
                    "input_tokens": _coerce_non_negative_int(
                        raw_stats.get("input_tokens", 0)
                    ),
                    "output_tokens": _coerce_non_negative_int(
                        raw_stats.get("output_tokens", 0)
                    ),
                }

        has_usage = any(
            usage_snapshot[field] > 0
            for field in (
                "audited_rows",
                "provider_requests",
                "cache_hits",
                "successful_requests",
                "failed_requests",
                "findings",
                "input_tokens",
                "output_tokens",
            )
        ) or bool(usage_snapshot["models"])
        if has_usage:
            snapshot["usage"] = usage_snapshot

    if (
        not snapshot["models"]
        and not snapshot["prompt_versions"]
        and "usage" not in snapshot
    ):
        return None
    return snapshot


def merge_llm_audit_metadata(
    shared_context: dict,
    metadata: dict[str, Any] | None,
) -> None:
    if not isinstance(metadata, dict):
        return

    target = _ensure_llm_audit_metadata(shared_context)
    models = target.setdefault("models", [])
    prompt_versions = target.setdefault("prompt_versions", [])

    for raw_model in metadata.get("models", []):
        model = str(raw_model).strip()
        if model and model not in models:
            models.append(model)

    for raw_prompt_version in metadata.get("prompt_versions", []):
        prompt_version = str(raw_prompt_version).strip()
        if prompt_version and prompt_version not in prompt_versions:
            prompt_versions.append(prompt_version)

    usage = metadata.get("usage")
    if not isinstance(usage, dict):
        return

    target_usage = _ensure_llm_usage_metadata(target)
    for field in (
        "audited_rows",
        "provider_requests",
        "cache_hits",
        "successful_requests",
        "failed_requests",
        "findings",
        "input_tokens",
        "output_tokens",
    ):
        _increment_counter(
            target_usage,
            field,
            _coerce_non_negative_int(usage.get(field, 0)),
        )

    raw_model_usage = usage.get("models", {})
    if not isinstance(raw_model_usage, dict):
        return

    for raw_model, raw_stats in raw_model_usage.items():
        model = str(raw_model).strip()
        if not model or not isinstance(raw_stats, dict):
            continue
        target_stats = _ensure_model_usage(target_usage, model)
        for field in (
            "provider_requests",
            "cache_hits",
            "successful_requests",
            "failed_requests",
            "findings",
            "input_tokens",
            "output_tokens",
        ):
            _increment_counter(
                target_stats,
                field,
                _coerce_non_negative_int(raw_stats.get(field, 0)),
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


def extract_llm_error_status_code(exc: Exception) -> int | None:
    for attr_name in ("status_code", "status"):
        status_code = _coerce_status_code(getattr(exc, attr_name, None))
        if status_code is not None:
            return status_code

    response = getattr(exc, "response", None)
    if response is not None:
        return _coerce_status_code(getattr(response, "status_code", None))

    return None


def _coerce_status_code(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_retriable_llm_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True

    error_name = type(exc).__name__.lower()
    if "timeout" in error_name:
        return True
    if "ratelimit" in error_name or ("rate" in error_name and "limit" in error_name):
        return True

    status_code = extract_llm_error_status_code(exc)
    return status_code == 429 or (
        status_code is not None and 500 <= status_code <= 599
    )


def describe_llm_error(exc: Exception) -> str:
    detail = str(exc).strip()
    if detail:
        return f"{type(exc).__name__}: {detail}"
    return type(exc).__name__


def configured_llm_models(llm_config: LLMConfig) -> list[str]:
    models = [llm_config.model]
    fallback_model = (llm_config.fallback_model or "").strip()
    if fallback_model and fallback_model != llm_config.model:
        models.append(fallback_model)
    return models


def normalize_findings(
    findings: list[dict[str, str]],
    *,
    model: str,
    prompt_version: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issue_meta = build_llm_issue_meta(
        model=model,
        prompt_version=prompt_version,
    )
    for i, f in enumerate(findings):
        issues.append(
            ValidationIssue(
                code=f"LLM_AUDIT_FINDING_{i + 1}",
                severity=f.get("severity", "warning"),
                message=f"Auditoria LLM: {f['issue']}",
                field=f.get("field"),
                meta=issue_meta,
            )
        )
    return issues


class LLMAuditRule(BaseRule):
    name: str = "llm_audit"

    def __init__(
        self,
        client: LLMClient | None = None,
        cache: LLMResponseCache | None = None,
    ) -> None:
        self._client = client
        self._cache = cache

    def _get_client(self) -> LLMClient:
        if self._client is not None:
            return self._client
        return get_default_client()

    def _get_cache(self) -> LLMResponseCache:
        if self._cache is not None:
            return self._cache
        return FileLLMResponseCache.from_env()

    def applies(self, context: ValidationContext) -> bool:
        if not context.tenant.llm.enabled:
            return False
        return context.normalized_row.get("flag_item_cadastrado_do_zero") == 1

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        llm_config: LLMConfig = context.tenant.llm

        try:
            loaded_prompt = load_prompt_template(
                context.tenant.tenant_id,
                llm_config.prompt_file,
            )
        except FileNotFoundError:
            return [
                ValidationIssue(
                    code="LLM_AUDIT_PROMPT_NOT_FOUND",
                    severity="warning",
                    message=f"Arquivo de prompt não encontrado: {llm_config.prompt_file}",
                    field=None,
                    meta=build_llm_issue_meta(
                        model=llm_config.model,
                        prompt_version=UNKNOWN_PROMPT_VERSION,
                    ),
                )
            ]

        prompt = format_prompt(loaded_prompt.template, context.normalized_row)
        cache_ttl_seconds = llm_config.cache_ttl_seconds
        cache_payload = normalize_llm_cache_payload(context.normalized_row)
        force_refresh = resolve_force_refresh(
            context.shared_context.get(LLM_FORCE_REFRESH_PARAM)
        )
        failures: list[LLMAttemptFailure] = []
        models = configured_llm_models(llm_config)
        record_llm_audit_row(context.shared_context)

        for index, model in enumerate(models):
            record_llm_audit_metadata(
                context.shared_context,
                model=model,
                prompt_version=loaded_prompt.version,
            )
            cache_key = build_llm_cache_key(
                tenant_id=context.tenant.tenant_id,
                prompt_version=loaded_prompt.version,
                model=model,
                payload=cache_payload,
            )

            if cache_ttl_seconds > 0:
                if force_refresh:
                    record_llm_cache_lookup(
                        context.tenant.tenant_id,
                        model,
                        outcome="bypass",
                    )
                else:
                    try:
                        cached_response = self._get_cache().get(
                            cache_key,
                            ttl_seconds=cache_ttl_seconds,
                        )
                    except Exception as exc:
                        logger.warning("LLM audit cache read failed: %s", exc)
                        cached_response = None

                    if cached_response is not None:
                        record_llm_cache_lookup(
                            context.tenant.tenant_id,
                            model,
                            outcome="hit",
                        )
                        record_llm_audit_cache_hit(
                            context.shared_context,
                            model=model,
                        )
                        findings = parse_llm_response(cached_response)
                        issues = normalize_findings(
                            findings,
                            model=model,
                            prompt_version=loaded_prompt.version,
                        )
                        record_llm_findings(
                            context.shared_context,
                            model=model,
                            findings_count=len(issues),
                        )
                        return issues

                    record_llm_cache_lookup(
                        context.tenant.tenant_id,
                        model,
                        outcome="miss",
                    )

            started_at = time.perf_counter()
            try:
                completion = normalize_completion_result(
                    self._get_client().complete(
                        model=model,
                        prompt=prompt,
                        temperature=llm_config.temperature,
                        max_tokens=llm_config.max_tokens,
                    )
                )
            except Exception as exc:
                record_llm_request(
                    context.tenant.tenant_id,
                    model,
                    (time.perf_counter() - started_at) * 1000.0,
                    outcome="error",
                )
                record_llm_audit_request(
                    context.shared_context,
                    model=model,
                    outcome="error",
                )
                logger.warning(
                    "LLM audit failed for row %d using model %s: %s",
                    context.row_index,
                    model,
                    exc,
                )
                failures.append(LLMAttemptFailure(model=model, error=exc))

                can_try_fallback = (
                    index == 0
                    and len(models) > 1
                    and is_retriable_llm_error(exc)
                )
                if can_try_fallback:
                    continue

                attempted_models = " -> ".join(failure.model for failure in failures)
                primary_failure = describe_llm_error(failures[0].error)
                final_failure = describe_llm_error(failures[-1].error)
                message = (
                    "Auditoria LLM falhou; "
                    f"modelos tentados: {attempted_models}; "
                    f"falha primária: {primary_failure}"
                )
                if len(failures) > 1:
                    message = f"{message}; falha final: {final_failure}"
                return [
                    ValidationIssue(
                        code="LLM_AUDIT_FAILURE",
                        severity="warning",
                        message=message,
                        field=None,
                        meta=build_llm_failure_meta(
                            model=model,
                            prompt_version=loaded_prompt.version,
                            failures=failures,
                        ),
                    )
                ]

            if cache_ttl_seconds > 0:
                try:
                    self._get_cache().set(cache_key, completion.text)
                except Exception as exc:
                    logger.warning("LLM audit cache write failed: %s", exc)

            record_llm_request(
                context.tenant.tenant_id,
                model,
                (time.perf_counter() - started_at) * 1000.0,
                outcome="success",
            )
            record_llm_audit_request(
                context.shared_context,
                model=model,
                outcome="success",
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
            )
            findings = parse_llm_response(completion.text)
            issues = normalize_findings(
                findings,
                model=model,
                prompt_version=loaded_prompt.version,
            )
            record_llm_findings(
                context.shared_context,
                model=model,
                findings_count=len(issues),
            )
            return issues

        return []
