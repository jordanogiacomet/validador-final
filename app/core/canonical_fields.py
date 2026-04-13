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
    "Item": "item",
    "Placa Anterior": "placa_anterior",
    "Descrição": "descricao",
    "Marca": "marca",
    "Modelo": "modelo",
    "NS": "ns",
    "Local": "local",
    "CC": "cc",
    "Complemento": "complemento",
    "Observação": "observacao",
}


def normalize_row(raw_row: dict[str, object]) -> dict[str, str | int | float | None]:
    """Normalize a raw row using canonical field mapping and derive flags."""
    normalized: dict[str, str | int | float | None] = {}

    for display_name, attr_name in CANONICAL_FIELD_MAP.items():
        value = raw_row.get(display_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            normalized[attr_name] = None
        else:
            normalized[attr_name] = value  # type: ignore[assignment]

    placa = normalized.get("placa_anterior")
    coletado, zero = derive_flags(placa)  # type: ignore[arg-type]
    normalized["flag_item_coletado"] = coletado
    normalized["flag_item_cadastrado_do_zero"] = zero

    return normalized
