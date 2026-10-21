"""Request and response bodies of `/admin/agent-config`."""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class AgentConfigOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    tone: str
    off_topic_policy: str
    refusal_message: str
    closing_message: str
    welcome_message: str
    llm_model: str
    daily_token_cap: int
    daily_cost_cap_micro_usd: int
    chat_rate_limit_per_minute: int


class CeilingsOut(BaseModel):
    max_daily_tokens: int
    max_daily_cost_micro_usd: int
    max_rate_limit_per_minute: int


class ModelInUseOut(BaseModel):
    provider: str
    model: str
    status: Literal["active", "disabled", "replay"]
    input_price_per_mtok: int
    output_price_per_mtok: int
    cost_cap_applies: bool = Field(description="False when the cost cap cannot bind (prices 0).")


class AgentConfigViewOut(BaseModel):
    version: int = Field(description="0 means the environment defaults, nothing stored yet.")
    config: AgentConfigOut
    ceilings: CeilingsOut
    allowed_models: list[str]
    model_in_use: ModelInUseOut
    updated_at: str | None
    updated_by: str | None = Field(description="User id of the last editor.")


class ChangeIn(BaseModel):
    """Either `changes` (a partial config) or `rollback_to_version`, never both."""

    model_config = ConfigDict(extra="forbid")

    changes: dict[str, Any] | None = Field(default=None, description="Fields to change.")
    rollback_to_version: StrictInt | None = Field(default=None, ge=1)
    base_version: StrictInt = Field(ge=0, description="The version the editor started from.")

    @model_validator(mode="after")
    def _exactly_one_change(self) -> Self:
        if (self.changes is None) == (self.rollback_to_version is None):
            raise ValueError("send changes or rollback_to_version, not both")
        return self


class WarningOut(BaseModel):
    code: str
    severity: Literal["info", "warning", "danger"]
    message_es: str


class PreviewOut(BaseModel):
    action: Literal["save", "rollback"]
    base_version: int
    diff: dict[str, list[Any]] = Field(description="Field -> [old, new].")
    warnings: list[WarningOut]
    requires_password: bool
    max_daily_cost_estimate_micro_usd: int
    confirmation_token: str
    expires_at: str
