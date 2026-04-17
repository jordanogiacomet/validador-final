from app.core.canonical_fields import (
    CANONICAL_FIELD_MAP,
    CANONICAL_FIELDS,
    DEFAULT_TENANT_COLUMNS,
    DERIVED_FLAGS,
    CanonicalInventoryRow,
    derive_flags,
    normalize_row,
)


class TestDeriveFlags:
    def test_collected_item_when_placa_present(self):
        assert derive_flags("OLD-001") == (1, 0)

    def test_zero_item_when_placa_none(self):
        assert derive_flags(None) == (0, 1)

    def test_zero_item_when_placa_empty_string(self):
        assert derive_flags("") == (0, 1)

    def test_zero_item_when_placa_whitespace_only(self):
        assert derive_flags("   ") == (0, 1)

    def test_collected_item_when_placa_has_surrounding_whitespace(self):
        assert derive_flags("  OLD-001  ") == (1, 0)

    def test_flags_are_mutually_exclusive(self):
        coletado, zero = derive_flags("ABC")
        assert coletado + zero == 1
        coletado, zero = derive_flags(None)
        assert coletado + zero == 1


class TestNormalizeRow:
    def test_default_mapping_preserves_canonical_fields(self):
        raw = {
            "Item": "A001",
            "Placa Anterior": "OLD-1",
            "Descrição": "Desktop",
            "Marca": "Dell",
            "Modelo": "7090",
            "NS": "SN123",
            "Local": "Sala 1",
            "CC": "CC-1",
            "Complemento": "i7 16GB",
            "Observação": "novo",
        }
        normalized = normalize_row(raw)
        assert normalized["item"] == "A001"
        assert normalized["placa_anterior"] == "OLD-1"
        assert normalized["descricao"] == "Desktop"
        assert normalized["marca"] == "Dell"
        assert normalized["modelo"] == "7090"
        assert normalized["ns"] == "SN123"
        assert normalized["local"] == "Sala 1"
        assert normalized["cc"] == "CC-1"
        assert normalized["complemento"] == "i7 16GB"
        assert normalized["observacao"] == "novo"

    def test_derives_coletado_flag_when_placa_present(self):
        normalized = normalize_row({"Item": "A001", "Placa Anterior": "OLD-1"})
        assert normalized["flag_item_coletado"] == 1
        assert normalized["flag_item_cadastrado_do_zero"] == 0

    def test_derives_zero_flag_when_placa_missing(self):
        normalized = normalize_row({"Item": "A001", "Placa Anterior": ""})
        assert normalized["flag_item_coletado"] == 0
        assert normalized["flag_item_cadastrado_do_zero"] == 1

    def test_derives_zero_flag_when_placa_column_is_missing(self):
        normalized = normalize_row({"Item": "A001", "Descrição": "Desktop"})
        assert normalized["flag_item_coletado"] == 0
        assert normalized["flag_item_cadastrado_do_zero"] == 1

    def test_blank_string_normalized_to_none(self):
        normalized = normalize_row({"Item": "   ", "Placa Anterior": None})
        assert normalized["item"] is None
        assert normalized["placa_anterior"] is None

    def test_missing_source_columns_become_none(self):
        normalized = normalize_row({"Item": "A001"})
        assert normalized["item"] == "A001"
        assert normalized["descricao"] is None
        assert normalized["flag_item_cadastrado_do_zero"] == 1

    def test_respects_custom_column_mapping(self):
        raw = {"codigo": "A001", "placa_old": "OLD-1", "desc": "Mouse"}
        mapping = {
            "item": "codigo",
            "placa_anterior": "placa_old",
            "descricao": "desc",
        }
        normalized = normalize_row(raw, column_mapping=mapping)
        assert normalized["item"] == "A001"
        assert normalized["placa_anterior"] == "OLD-1"
        assert normalized["descricao"] == "Mouse"
        assert normalized["flag_item_coletado"] == 1

    def test_source_column_lookup_is_accent_insensitive(self):
        raw = {"item": "A001", "descricao": "Desktop", "observacao": "teste"}
        normalized = normalize_row(raw)
        assert normalized["item"] == "A001"
        assert normalized["descricao"] == "Desktop"
        assert normalized["observacao"] == "teste"


class TestCanonicalConstants:
    def test_canonical_fields_tuple_matches_domain(self):
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

    def test_derived_flags_tuple_matches_domain(self):
        assert DERIVED_FLAGS == (
            "flag_item_coletado",
            "flag_item_cadastrado_do_zero",
        )

    def test_field_map_inverts_default_tenant_columns(self):
        for attr_name, display_name in DEFAULT_TENANT_COLUMNS.items():
            assert CANONICAL_FIELD_MAP[display_name] == attr_name


class TestCanonicalInventoryRow:
    def test_defaults_are_none_and_flags_zero(self):
        row = CanonicalInventoryRow()
        for field in (
            "item",
            "placa_anterior",
            "descricao",
            "marca",
            "modelo",
            "ns",
            "local",
            "cc",
            "complemento",
            "observacao",
        ):
            assert getattr(row, field) is None
        assert row.flag_item_coletado == 0
        assert row.flag_item_cadastrado_do_zero == 0

    def test_accepts_normalized_row_dict(self):
        normalized = normalize_row({"Item": "A001", "Placa Anterior": "OLD"})
        row = CanonicalInventoryRow(**normalized)
        assert row.item == "A001"
        assert row.placa_anterior == "OLD"
        assert row.flag_item_coletado == 1
        assert row.flag_item_cadastrado_do_zero == 0
