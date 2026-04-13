from abc import ABC, abstractmethod

from app.core.context import ValidationContext
from app.core.issue import ValidationIssue


class BaseRule(ABC):
    name: str = "base_rule"

    @abstractmethod
    def applies(self, context: ValidationContext) -> bool:
        raise NotImplementedError

    @abstractmethod
    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        raise NotImplementedError