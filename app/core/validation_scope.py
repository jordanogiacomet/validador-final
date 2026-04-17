from enum import StrEnum


class ValidationScope(StrEnum):
    ZERO_ITEMS = "zero_items"
    ALL_ITEMS = "all_items"
    DUPLICATE_ITEMS = "duplicate_items"


DEFAULT_VALIDATION_SCOPE = ValidationScope.ZERO_ITEMS
VALIDATION_SCOPE_PARAM = "validation_scope"


def parse_validation_scope(value: object) -> ValidationScope:
    if isinstance(value, ValidationScope):
        return value

    if isinstance(value, str):
        try:
            return ValidationScope(value)
        except ValueError:
            return DEFAULT_VALIDATION_SCOPE

    return DEFAULT_VALIDATION_SCOPE
