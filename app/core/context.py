from pydantic import BaseModel, Field

from app.core.tenant_config import TenantConfig


class ValidationContext(BaseModel):
    tenant: TenantConfig
    row_index: int
    raw_row: dict[str, object] = Field(default_factory=dict)
    normalized_row: dict[str, str | int | float | None] = Field(default_factory=dict)
    all_rows: list[dict[str, str | int | float | None]] = Field(default_factory=list)
    shared_context: dict = Field(default_factory=dict)
