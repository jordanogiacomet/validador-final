from pydantic import BaseModel, Field


class CategoryConfig(BaseModel):
    name: str
    display_name: str = ""
    keywords: list[str] = Field(default_factory=list)
    critical_checks: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    field_help: dict[str, str] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    enabled: bool = False
    model: str = ""
    temperature: float = 0.0
    max_tokens: int = 1024
    prompt_file: str = ""


class CSVConfig(BaseModel):
    delimiter: str = ","
    encoding: str = "utf-8"


class TenantConfig(BaseModel):
    tenant_id: str
    display_name: str
    columns: dict[str, str] = Field(default_factory=dict)
    enabled_rules: list[str] = Field(default_factory=list)
    disabled_rules: list[str] = Field(default_factory=list)
    thresholds: dict[str, int | float | str | bool] = Field(default_factory=dict)
    categories: list[CategoryConfig] = Field(default_factory=list)
    csv: CSVConfig = Field(default_factory=CSVConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


DEFAULT_TENANT_ID = "default"
