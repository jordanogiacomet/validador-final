from app.core.canonical_fields import (
    CANONICAL_FIELDS,
    DERIVED_FLAGS,
    derive_flags,
    normalize_row,
)


def test_derive_flags_with_non_empty_placa_marks_collected():
    coletado, zero = derive_flags("PL-123")
    assert coletado == 1
    assert zero == 0


def test_derive_flags_with_none_marks_zero_created():
    coletado, zero = derive_flags(None)
    assert coletado == 0
    assert zero == 1


def test_derive_flags_with_empty_string_marks_zero_created():
    coletado, zero = derive_flags("")
    assert coletado == 0
    assert zero == 1


def test_derive_flags_with_whitespace_only_marks_zero_created():
    coletado, zero = derive_flags("   ")
    assert coletado == 0
    assert zero == 1


def test_derive_flags_flags_are_mutually_exclusive():
    for placa in ["A", None, "", " ", "0", "abc-1"]:
        coletado, zero = derive_flags(placa)
        assert coletado + zero == 1


def test_normalize_row_sets_collected_flag_when_placa_present():
    raw = {
        "Item": "123",
        "Placa Anterior": "PL-001",
        "Descrição": "Notebook",
    }
    normalized = normalize_row(raw)
    assert normalized["flag_item_coletado"] == 1
    assert normalized["flag_item_cadastrado_do_zero"] == 0


def test_normalize_row_sets_zero_flag_when_placa_absent():
    raw = {
        "Item": "456",
        "Placa Anterior": "",
        "Descrição": "Cadeira",
    }
    normalized = normalize_row(raw)
    assert normalized["flag_item_coletado"] == 0
    assert normalized["flag_item_cadastrado_do_zero"] == 1


def test_normalize_row_sets_zero_flag_when_placa_missing_column():
    raw = {
        "Item": "789",
        "Descrição": "Mesa",
    }
    normalized = normalize_row(raw)
    assert normalized["flag_item_coletado"] == 0
    assert normalized["flag_item_cadastrado_do_zero"] == 1


def test_normalize_row_respects_tenant_column_mapping_for_placa():
    raw = {
        "asset_id": "42",
        "old_tag": "OLD-42",
        "description": "Monitor",
    }
    mapping = {
        "item": "asset_id",
        "placa_anterior": "old_tag",
        "descricao": "description",
    }
    normalized = normalize_row(raw, column_mapping=mapping)
    assert normalized["item"] == "42"
    assert normalized["placa_anterior"] == "OLD-42"
    assert normalized["flag_item_coletado"] == 1
    assert normalized["flag_item_cadastrado_do_zero"] == 0


def test_canonical_fields_constants_are_stable():
    assert CANONICAL_FIELDS == (
        "Item",
        "Placa Anterior",
        "Descrição",
        "Marca",
        "Modelo",
        "NS",
        "Local",
        "CC",
        "Complemento",
        "Observação",
    )
    assert DERIVED_FLAGS == (
        "flag_item_coletado",
        "flag_item_cadastrado_do_zero",
    )
