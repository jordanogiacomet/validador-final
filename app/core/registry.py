from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.rules.base import BaseRule

RULE_REGISTRY: dict[str, BaseRule] = {}


def register_rule(rule: BaseRule) -> None:
    RULE_REGISTRY[rule.name] = rule


def get_rule(name: str) -> BaseRule | None:
    return RULE_REGISTRY.get(name)
