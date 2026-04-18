from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.core.normalization import BrandModelNormalizer, normalize_lookup_key
from app.rules.base import BaseRule

_NORMALIZER_CACHE_KEY = "_brand_model_consistency_normalizer"


class BrandModelConsistencyRule(BaseRule):
    name: str = "brand_model_consistency"

    def applies(self, context: ValidationContext) -> bool:
        modelo = context.normalized_row.get("modelo")
        return bool(modelo and str(modelo).strip())

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        modelo = context.normalized_row.get("modelo")
        marca = context.normalized_row.get("marca")
        if not modelo or not str(modelo).strip():
            return []
        if not marca or not str(marca).strip():
            return []

        normalizer = self._get_normalizer(context)
        expected_brand = normalizer.infer_brand_for_model(modelo)
        if expected_brand is None:
            return []

        informed_brand_key = normalize_lookup_key(str(marca))
        expected_brand_key = normalize_lookup_key(expected_brand)
        if informed_brand_key == expected_brand_key:
            return []

        return [
            ValidationIssue(
                code="BRAND_MODEL_CONSISTENCY_MISMATCH",
                severity="warning",
                message=(
                    f"Modelo '{modelo}' é associado à marca '{expected_brand}', "
                    f"mas a linha informa '{marca}'"
                ),
                field="marca",
            )
        ]

    def _get_normalizer(self, context: ValidationContext) -> BrandModelNormalizer:
        cached = context.shared_context.get(_NORMALIZER_CACHE_KEY)
        if isinstance(cached, BrandModelNormalizer):
            return cached

        normalizer = BrandModelNormalizer.from_config(context.tenant.normalization)
        context.shared_context[_NORMALIZER_CACHE_KEY] = normalizer
        return normalizer
