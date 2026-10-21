"""Request and response bodies of `/admin/agent-config`."""

from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictInt,
    field_validator,
    model_validator,
)

MAX_CHANGE_KEYS = 12
MAX_CHANGE_STRING = 1000


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
    free: bool = Field(description="True for a free model (`:free` suffix, no cost).")


class AgentConfigViewOut(BaseModel):
    version: int = Field(description="0 means the environment defaults, nothing stored yet.")
    config: AgentConfigOut
    ceilings: CeilingsOut
    allowed_models: list[str]
    model_in_use: ModelInUseOut
    defaults_out_of_bounds: list[str] = Field(
        description="Fields of the active config outside the validation bounds (version 0 can "
        "carry environment values such as a cap of 0): a change must fix all of them at once."
    )
    updated_at: str | None
    updated_by: str | None = Field(description="User id of the last editor.")


class ChangeIn(BaseModel):
    """Either `changes` (a partial config) or `rollback_to_version`, never both."""

    model_config = ConfigDict(extra="forbid")

    changes: dict[str, Any] | None = Field(default=None, description="Fields to change.")
    rollback_to_version: StrictInt | None = Field(default=None, ge=1)
    base_version: StrictInt = Field(ge=0, description="The version the editor started from.")

    @field_validator("changes")
    @classmethod
    def _bounded_changes(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """Cap the size before any normalization runs on it (a config has 9 fields)."""
        if value is not None and (
            len(value) > MAX_CHANGE_KEYS
            or any(len(k) > 64 for k in value)
            or any(isinstance(v, str) and len(v) > MAX_CHANGE_STRING for v in value.values())
        ):
            raise ValueError("changes are too large")
        return value

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
    max_daily_cost_estimate_micro_usd: int | None = Field(
        description="Worst case per day; null when the price of the selected model is unknown."
    )
    confirmation_token: str
    expires_at: str


class ApplyIn(ChangeIn):
    confirmation_token: str = Field(min_length=1, max_length=2000)
    typed_confirmation: str = Field(max_length=32, description='Exactly "APLICAR".')
    password: SecretStr | None = Field(
        default=None, max_length=256, description="Required when requires_password was true."
    )
    note: str | None = Field(default=None, max_length=200)


class ApplyOut(BaseModel):
    version: int
    config: AgentConfigOut
    applied_at: str


class HistoryItemOut(BaseModel):
    version: int
    created_at: str
    created_by: str | None = Field(description="User id of the editor.")
    note: str | None
    action: Literal["save", "rollback"]
    diff: dict[str, list[Any]] = Field(description="Field -> [old, new].")
