from concurrent.futures import ThreadPoolExecutor

from app.core.llm_cache import (
    FileLLMResponseCache,
    build_llm_cache_key,
    normalize_llm_cache_payload,
    resolve_force_refresh,
)


def test_normalize_llm_cache_payload_uses_prompt_fields_with_stable_whitespace():
    payload = normalize_llm_cache_payload(
        {
            "descricao": "  Mesa   executiva ",
            "marca": None,
            "modelo": "M1",
            "ns": 123,
            "complemento": "com   gavetas",
            "observacao": "",
            "ignored": "fora do prompt",
        }
    )

    assert payload == {
        "descricao": "Mesa executiva",
        "marca": "",
        "modelo": "M1",
        "ns": "123",
        "complemento": "com gavetas",
        "observacao": "",
    }


def test_llm_cache_key_is_stable_for_equivalent_payloads():
    key_a = build_llm_cache_key(
        tenant_id="tenant",
        prompt_version="v1",
        model="model-a",
        payload={"descricao": "Mesa", "marca": ""},
    )
    key_b = build_llm_cache_key(
        tenant_id="tenant",
        prompt_version="v1",
        model="model-a",
        payload={"marca": "", "descricao": "Mesa"},
    )

    assert key_a == key_b


def test_file_llm_response_cache_persists_between_instances(tmp_path):
    now = 1000.0
    cache_path = tmp_path / "llm_cache.json"
    cache = FileLLMResponseCache(cache_path, clock=lambda: now)
    cache.set("key", "response")

    reloaded_cache = FileLLMResponseCache(cache_path, clock=lambda: now)

    assert reloaded_cache.get("key", ttl_seconds=60) == "response"


def test_file_llm_response_cache_expires_stale_entries(tmp_path):
    now = 1000.0
    cache = FileLLMResponseCache(tmp_path / "llm_cache.json", clock=lambda: now)
    cache.set("key", "response")

    now = 1100.0

    assert cache.get("key", ttl_seconds=60) is None


def test_file_llm_response_cache_handles_parallel_writes(tmp_path):
    cache_path = tmp_path / "llm_cache.json"

    def write_entry(index: int) -> None:
        FileLLMResponseCache(cache_path, clock=lambda: 1000.0).set(
            f"key-{index}",
            f"response-{index}",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write_entry, range(8)))

    cache = FileLLMResponseCache(cache_path, clock=lambda: 1000.0)
    for index in range(8):
        assert cache.get(f"key-{index}", ttl_seconds=60) == f"response-{index}"


def test_file_llm_response_cache_prunes_expired_entries(tmp_path):
    now = 1000.0
    cache = FileLLMResponseCache(tmp_path / "llm_cache.json", clock=lambda: now)
    cache.set("old-key", "old-response")

    now = 1100.0
    cache.set("fresh-key", "fresh-response")

    result = cache.prune_expired(ttl_seconds=60)

    assert result.removed_entries == 1
    assert result.remaining_entries == 1
    assert cache.get("old-key", ttl_seconds=600) is None
    assert cache.get("fresh-key", ttl_seconds=600) == "fresh-response"


def test_file_llm_response_cache_prune_dry_run_keeps_entries(tmp_path):
    now = 1000.0
    cache = FileLLMResponseCache(tmp_path / "llm_cache.json", clock=lambda: now)
    cache.set("old-key", "old-response")

    now = 1100.0
    result = cache.prune_expired(ttl_seconds=60, dry_run=True)

    assert result.removed_entries == 1
    assert result.remaining_entries == 0
    assert cache.get("old-key", ttl_seconds=600) == "old-response"


def test_resolve_force_refresh_accepts_boolean_and_string_values():
    assert resolve_force_refresh(True) is True
    assert resolve_force_refresh("true") is True
    assert resolve_force_refresh("1") is True
    assert resolve_force_refresh(False) is False
    assert resolve_force_refresh(None) is False
