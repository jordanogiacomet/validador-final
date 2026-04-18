from typing import Any

from pydantic import BaseModel


class ValidationIssue(BaseModel):
    code: str
    severity: str
    message: str
    field: str | None = None
    meta: dict[str, Any] | None = None
