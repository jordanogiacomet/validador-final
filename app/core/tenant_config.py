from pydantic import BaseModel, Field


class TenantConfig(BaseModel):
    tenant_id: str
    display_name: str
    columns: dict[str, str] = Field(default_factory=dict)
    enabled_rules: list[str] = Field(default_factory=list)
    disabled_rules: list[str] = Field(default_factory=list)
    thresholds: dict[str, int | float | str | bool] = Field(default_factory=dict)
    categories: list[dict] = Field(default_factory=list)
    llm: dict[str, str | int | bool] = Field(default_factory=dict)