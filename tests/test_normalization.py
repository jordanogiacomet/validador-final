from app.core.normalization import BrandModelNormalizer
from app.core.tenant_config import NormalizationConfig


def test_brand_model_normalizer_applies_exact_aliases() -> None:
    normalizer = BrandModelNormalizer.from_config(
        NormalizationConfig(
            brand_aliases={"Samsung Eletronics": "Samsung"},
            model_aliases={"ThinkPad T14 G1": "ThinkPad T14 Gen 1"},
        )
    )

    normalized = normalizer.normalize_row(
        {
            "marca": "Samsung Eletronics",
            "modelo": "ThinkPad T14 G1",
            "descricao": "Notebook",
        }
    )

    assert normalized["marca"] == "Samsung"
    assert normalized["modelo"] == "ThinkPad T14 Gen 1"
    assert normalized["descricao"] == "Notebook"


def test_brand_model_normalizer_matches_case_and_accent_insensitively() -> None:
    normalizer = BrandModelNormalizer.from_config(
        NormalizationConfig(
            brand_aliases={"samsúng": "Samsung"},
            model_aliases={"élitebook 840 g5": "EliteBook 840 G5"},
        )
    )

    normalized = normalizer.normalize_row(
        {
            "marca": "SAMSUNG",
            "modelo": "ELITEBOOK 840 G5",
        }
    )

    assert normalized["marca"] == "Samsung"
    assert normalized["modelo"] == "EliteBook 840 G5"


def test_brand_model_normalizer_keeps_original_value_when_alias_is_missing() -> None:
    normalizer = BrandModelNormalizer.from_config(
        NormalizationConfig(brand_aliases={"lg electronics": "LG"})
    )

    normalized = normalizer.normalize_row(
        {
            "marca": "Philips",
            "modelo": "55PUG7908",
        }
    )

    assert normalized["marca"] == "Philips"
    assert normalized["modelo"] == "55PUG7908"


def test_brand_model_normalizer_handles_missing_dictionary() -> None:
    normalizer = BrandModelNormalizer.from_config(None)

    normalized = normalizer.normalize_row(
        {
            "marca": "Samsúng",
            "modelo": "ThinkPad T14 G1",
        }
    )

    assert normalized["marca"] == "Samsúng"
    assert normalized["modelo"] == "ThinkPad T14 G1"
