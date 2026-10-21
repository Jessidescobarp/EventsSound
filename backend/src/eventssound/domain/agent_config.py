"""Admin-editable agent configuration: tone, texts and technical limits, all bounded.

Only behavior and limits live here. The provider and every API key are NOT part of it and are
never stored. `validate_config` is the single gate for untrusted input (admin edits, stored
JSON); errors name the field, never the value.
"""

import re
import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Any, Literal, get_args
from uuid import UUID

from .errors import InvalidAgentConfig

Tone = Literal["formal", "cercano", "neutral"]
OffTopicPolicy = Literal["strict", "normal"]
TONES: tuple[str, ...] = get_args(Tone)
OFF_TOPIC_POLICIES: tuple[str, ...] = get_args(OffTopicPolicy)

# Hard ceilings, enforced here whatever an admin submits. Tokens and cost are 10x the Settings
# defaults (100_000 tokens, 1_000_000 micro-USD = 1 USD per day): room to raise the limits for a
# busy day, while a typo or a compromised admin account is bounded to about 10 USD per day.
# 60 requests per minute is one per second per client, far above any human typing in a chat.
HARD_MAX_DAILY_TOKENS = 1_000_000
HARD_MAX_DAILY_COST_MICRO_USD = 10_000_000
HARD_MAX_RATE_LIMIT_PER_MINUTE = 60
MAX_TEXT_CHARS = 400

# The single definition of a provider model id; the OpenRouter adapter imports it. It admits the
# OpenRouter `:free` suffix (":" is allowed) but no "//", so a URL-like string is never an id.
MODEL_ID_PATTERN = re.compile(r"(?!.*//)[A-Za-z0-9][A-Za-z0-9._:/~+-]{0,119}")

# Extra per-field rule on top of _FORBIDDEN_TEXT. The closing is appended to quotes without
# verification and the refusal is shown as-is, so neither may carry a number, price or percent
# (a price-like string would read as part of the quote). The welcome keeps digits (opening hours).
_MONEY_SYMBOLS = re.compile(r"[$%]")
_ANY_NUMBER = re.compile(r"[\d$%]")
_TEXT_FIELDS = {
    "refusal_message": _ANY_NUMBER,
    "closing_message": _ANY_NUMBER,
    "welcome_message": _MONEY_SYMBOLS,
}
MAX_TEXT_LINES = 3
_FORBIDDEN_CATEGORIES = frozenset(
    {"Cc", "Cf", "Zl", "Zp"}
)  # control, format (zero-width, bidi), separators
_FORBIDDEN_TEXT = (
    re.compile(r"[<>\[\]`&]"),  # markup, markdown links and code, HTML entities
    re.compile(r"https?://|www\.", re.IGNORECASE),
    re.compile(r"\b[\w-]+\.[a-z]{2,}\b", re.IGNORECASE),  # any domain-like "name.tld"
    re.compile(r"\S@\S"),  # e-mail-like
    re.compile(r"\d{7}"),  # a long digit run
    re.compile(r"\+?\(?\d{2,4}\)?[\s.-]\d{3,4}[\s.-]\d{3,4}|\b\d{3}[\s.-]\d{4}\b"),  # phone formats
)


@dataclass(frozen=True)
class AgentConfig:
    tone: Tone
    off_topic_policy: OffTopicPolicy
    refusal_message: str
    closing_message: str
    welcome_message: str
    llm_model: str
    daily_token_cap: int
    daily_cost_cap_micro_usd: int
    chat_rate_limit_per_minute: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: object, allowed_models: Collection[str] | None) -> "AgentConfig":
        """Strictly parse and validate; `allowed_models=None` skips only the allowlist check."""
        names = {f.name for f in fields(cls)}
        if not isinstance(data, Mapping) or set(data) != names:
            raise InvalidAgentConfig("config must have exactly the known fields")
        return validate_config(cls(**data), allowed_models)


@dataclass(frozen=True)
class StoredAgentConfig:
    config: AgentConfig
    version: int
    created_at: datetime
    created_by_user_id: UUID | None
    note: str | None = None


def _normalize_text(text: str) -> str:
    """NFKC, trimmed lines, runs of blank lines collapsed to one (so fullwidth tricks fold)."""
    lines = [
        line.strip()
        for line in unicodedata.normalize("NFKC", text).replace("\r\n", "\n").split("\n")
    ]
    kept = [line for i, line in enumerate(lines) if line or (i and lines[i - 1])]
    return "\n".join(kept).strip()


def _check_text(name: str, value: object, extra: re.Pattern[str]) -> str:
    if not isinstance(value, str):
        raise InvalidAgentConfig(f"{name} must be text")
    text = _normalize_text(value)
    if not 1 <= len(text) <= MAX_TEXT_CHARS or text.count("\n") + 1 > MAX_TEXT_LINES:
        raise InvalidAgentConfig(
            f"{name} must have 1 to {MAX_TEXT_CHARS} characters and at most {MAX_TEXT_LINES} lines"
        )
    if any(c != "\n" and unicodedata.category(c) in _FORBIDDEN_CATEGORIES for c in text):
        raise InvalidAgentConfig(f"{name} has control or invisible characters")
    if extra.search(text):
        raise InvalidAgentConfig(f"{name} must not contain numbers, prices or percentages")
    if any(pattern.search(text) for pattern in _FORBIDDEN_TEXT):
        raise InvalidAgentConfig(f"{name} has forbidden content (markup, links, e-mail or phone)")
    return text


def _check_int(name: str, value: object, ceiling: int) -> int:
    if type(value) is not int or not 1 <= value <= ceiling:
        raise InvalidAgentConfig(f"{name} must be an integer within 1..{ceiling}")
    return value


def validate_config(config: AgentConfig, allowed_models: Collection[str] | None) -> AgentConfig:
    """Return the normalized (stripped) config or raise InvalidAgentConfig."""
    if config.tone not in TONES:
        raise InvalidAgentConfig(f"tone must be one of {TONES}")
    if config.off_topic_policy not in OFF_TOPIC_POLICIES:
        raise InvalidAgentConfig(f"off_topic_policy must be one of {OFF_TOPIC_POLICIES}")
    model = config.llm_model
    if not isinstance(model, str) or not MODEL_ID_PATTERN.fullmatch(model):
        raise InvalidAgentConfig("llm_model must be a provider model id such as vendor/name")
    if allowed_models is not None and model not in allowed_models:
        raise InvalidAgentConfig("llm_model is not in the allowed list")
    texts = {
        name: _check_text(name, getattr(config, name), rule) for name, rule in _TEXT_FIELDS.items()
    }
    return AgentConfig(
        tone=config.tone,
        off_topic_policy=config.off_topic_policy,
        llm_model=model,
        daily_token_cap=_check_int(
            "daily_token_cap", config.daily_token_cap, HARD_MAX_DAILY_TOKENS
        ),
        daily_cost_cap_micro_usd=_check_int(
            "daily_cost_cap_micro_usd",
            config.daily_cost_cap_micro_usd,
            HARD_MAX_DAILY_COST_MICRO_USD,
        ),
        chat_rate_limit_per_minute=_check_int(
            "chat_rate_limit_per_minute",
            config.chat_rate_limit_per_minute,
            HARD_MAX_RATE_LIMIT_PER_MINUTE,
        ),
        **texts,
    )


MAX_NOTE_CHARS = 200


def validate_note(note: object) -> str | None:
    """The optional change note: trimmed, at most 200 characters, one line, no invisible chars."""
    if note is None:
        return None
    if not isinstance(note, str):
        raise InvalidAgentConfig("note must be text")
    text = unicodedata.normalize("NFKC", note).strip()
    if len(text) > MAX_NOTE_CHARS or any(
        unicodedata.category(c) in _FORBIDDEN_CATEGORIES for c in text
    ):
        raise InvalidAgentConfig(f"note must be one line of at most {MAX_NOTE_CHARS} characters")
    return text or None


@dataclass(frozen=True)
class AuditEntry:
    """One applied change: who, when, what (`field -> [old, new]`) and whether a rollback."""

    version: int
    at: datetime
    user_id: UUID | None
    action: str  # "save" or "rollback"
    diff: dict[str, Any]
    note: str | None
