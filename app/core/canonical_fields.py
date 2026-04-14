import unicodedata
from collections.abc import Collection

from pydantic import BaseModel, Field

CANONICAL_FIELDS = (
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

DERIVED_FLAGS = (
    "flag_item_coletado",
    "flag_item_cadastrado_do_zero",
)

DEFAULT_TENANT_COLUMNS: dict[str, str] = {
    "item": "Item",
    "placa_anterior": "Placa Anterior",
    "descricao": "Descrição",
    "marca": "Marca",
    "modelo": "Modelo",
    "ns": "NS",
    "local": "Local",
    "cc": "CC",
    "complemento": "Complemento",
    "observacao": "Observação",
}


def _normalize_source_column_key(value: str) -> str:
    text = value.removeprefix("\ufeff").strip()
    text = " ".join(text.split())
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return unicodedata.normalize("NFKC", without_accents).casefold()


def build_source_column_lookup(available_columns: Collection[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for column_name in available_columns:
        lookup.setdefault(_normalize_source_column_key(column_name), column_name)
    return lookup


def resolve_source_column_name(
    source_column: str,
    available_columns: Collection[str],
    column_lookup: dict[str, str] | None = None,
) -> str | None:
    if source_column in available_columns:
        return source_column

    lookup = (
        column_lookup
        if column_lookup is not None
        else build_source_column_lookup(available_columns)
    )
    return lookup.get(_normalize_source_column_key(source_column))


class CanonicalInventoryRow(BaseModel):
    """Canonical representation of a single inventory row.

    Collected item (flag_item_coletado=1): an asset found during physical inventory that
    already existed in a prior inventory — identified by a non-empty Placa Anterior.

    Zero-created item (flag_item_cadastrado_do_zero=1): an asset registered for the first
    time during the current inventory — identified by an empty/absent Placa Anterior.
    These items receive stricter quality checks because they lack prior identification data.
    """

    item: str | None = Field(default=None, description="Unique asset tag or identifier")
    placa_anterior: str | None = Field(
        default=None, description="Previous inventory tag; empty means zero-created"
    )
    descricao: str | None = Field(default=None, description="Asset description")
    marca: str | None = Field(default=None, description="Brand / manufacturer")
    modelo: str | None = Field(default=None, description="Model identifier")
    ns: str | None = Field(default=None, description="Serial number")
    local: str | None = Field(default=None, description="Physical location")
    cc: str | None = Field(default=None, description="Cost center")
    complemento: str | None = Field(
        default=None, description="Complementary identification details"
    )
    observacao: str | None = Field(default=None, description="Observation / notes")

    flag_item_coletado: int = Field(default=0, description="1 if item existed in prior inventory")
    flag_item_cadastrado_do_zero: int = Field(
        default=0, description="1 if item was created from scratch in current inventory"
    )


def derive_flags(placa_anterior: str | None) -> tuple[int, int]:
    """Derive collection flags from Placa Anterior.

    Returns (flag_item_coletado, flag_item_cadastrado_do_zero).
    """
    has_placa = bool(placa_anterior and str(placa_anterior).strip())
    return (int(has_placa), int(not has_placa))


CANONICAL_FIELD_MAP: dict[str, str] = {
    display_name: attr_name for attr_name, display_name in DEFAULT_TENANT_COLUMNS.items()
}


def normalize_row(
    raw_row: dict[str, object],
    column_mapping: dict[str, str] | None = None,
) -> dict[str, str | int | float | None]:
    """Normalize a raw row using tenant column mapping and derive flags."""
    normalized: dict[str, str | int | float | None] = {}
    column_lookup = build_source_column_lookup(raw_row.keys())
    for attr_name, default_source_column in DEFAULT_TENANT_COLUMNS.items():
        source_column = (
            column_mapping.get(attr_name, default_source_column)
            if column_mapping is not None
            else default_source_column
        )
        resolved_source_column = resolve_source_column_name(
            source_column,
            raw_row.keys(),
            column_lookup,
        )
        value = raw_row.get(resolved_source_column) if resolved_source_column else None
        if value is None or (isinstance(value, str) and not value.strip()):
            normalized[attr_name] = None
        else:
            normalized[attr_name] = value  # type: ignore[assignment]

    placa = normalized.get("placa_anterior")
    coletado, zero = derive_flags(placa)  # type: ignore[arg-type]
    normalized["flag_item_coletado"] = coletado
    normalized["flag_item_cadastrado_do_zero"] = zero

    return normalized
