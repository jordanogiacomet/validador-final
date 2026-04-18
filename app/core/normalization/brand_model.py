import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.core.tenant_config import NormalizationConfig

RowValue = str | int | float | None
RowType = dict[str, RowValue]


def normalize_lookup_key(value: str) -> str:
    text = " ".join(value.strip().split())
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return unicodedata.normalize("NFKC", without_accents).casefold()


def _build_alias_lookup(aliases: Mapping[str, str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for alias, canonical_value in aliases.items():
        normalized_alias = normalize_lookup_key(alias)
        if normalized_alias:
            lookup[normalized_alias] = canonical_value
    return lookup


def _normalize_alias_value(
    value: RowValue,
    lookup: Mapping[str, str],
) -> RowValue:
    if not isinstance(value, str):
        return value

    normalized_value = normalize_lookup_key(value)
    if not normalized_value:
        return value

    return lookup.get(normalized_value, value)


@dataclass(frozen=True)
class BrandModelNormalizer:
    brand_lookup: dict[str, str] = field(default_factory=dict)
    model_lookup: dict[str, str] = field(default_factory=dict)
    model_brand_lookup: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_config(
        cls,
        config: NormalizationConfig | None,
    ) -> "BrandModelNormalizer":
        if config is None:
            return cls()

        model_lookup = _build_alias_lookup(config.model_aliases)
        model_brand_lookup = _build_alias_lookup(config.model_brands)
        for alias, canonical_model in model_lookup.items():
            canonical_model_key = normalize_lookup_key(canonical_model)
            canonical_brand = model_brand_lookup.get(canonical_model_key)
            if canonical_brand is not None:
                model_brand_lookup.setdefault(alias, canonical_brand)

        return cls(
            brand_lookup=_build_alias_lookup(config.brand_aliases),
            model_lookup=model_lookup,
            model_brand_lookup=model_brand_lookup,
        )

    def normalize_row(
        self,
        normalized_row: RowType,
    ) -> RowType:
        row = dict(normalized_row)
        row["marca"] = _normalize_alias_value(row.get("marca"), self.brand_lookup)
        row["modelo"] = _normalize_alias_value(row.get("modelo"), self.model_lookup)
        return row

    def infer_brand_for_model(self, model: RowValue) -> str | None:
        if not isinstance(model, str):
            return None

        normalized_model = normalize_lookup_key(model)
        if not normalized_model:
            return None

        canonical_model = self.model_lookup.get(normalized_model, model)
        canonical_model_key = normalize_lookup_key(canonical_model)
        if not canonical_model_key:
            return None

        return self.model_brand_lookup.get(canonical_model_key)
