"""Input sanitation and the injection heuristic for the quote agent.

Pure stdlib on purpose: the application layer owns these rules even if the graph
runner is replaced, and they must stay importable without any adapter.
"""

import re
import unicodedata

_MAX_MESSAGES_DEFAULT = 16  # keep equal to schemas.MAX_MESSAGES and frontend api/chat.ts
_MAX_MESSAGE_CHARS_DEFAULT = 1000
_MAX_TOTAL_CHARS_DEFAULT = 4000

_CONTROL_OR_ZERO_WIDTH = re.compile(
    "[\x00-\x1f\x7f\u0080-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2069\u180e\ufeff]"
)
_WHITESPACE = re.compile(r"\s+")
# A long run of base64 alphabet is treated as a payload, not prose (I10).
# ponytail: standard alphabet only (no URL-safe or wrapped blobs); the gate is a heuristic.
_BASE64_BLOB = re.compile(r"[A-Za-z0-9+/]{160,}={0,2}")

# Phrase-level patterns only (never a bare word such as "instrucciones"), already
# accent-folded and lowercased; matched against the sanitized, folded text.
_INJECTION_PHRASES = (
    "ignora las instrucciones",
    "ignora todas las instrucciones",
    "ignorar las instrucciones",
    "ignorar todas las instrucciones",
    "ignore previous",
    "ignore all instructions",
    "ignore your instructions",
    "olvida lo anterior",
    "olvida las instrucciones",
    "system prompt",
    "prompt de sistema",
    "revela tu prompt",
    "revela el prompt",
    "muestra tu prompt",
    "muestra el prompt",
    "eres ahora",
    "developer mode",
    "modo desarrollador",
    "jailbreak",
)


def neutralize_delimiters(text: str) -> str:
    """Remove angle brackets so a forged `<tag>` comes out as harmless text."""
    return text.replace("<", "").replace(">", "")


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    ).lower()


def looks_like_injection(text: str) -> bool:
    """Heuristic gate: refuse without an LLM call. NOT the safety layer (see design D27)."""
    if _BASE64_BLOB.search(text):
        return True
    folded = _fold(text)
    return any(phrase in folded for phrase in _INJECTION_PHRASES)


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL_OR_ZERO_WIDTH.sub(" ", text)
    text = neutralize_delimiters(text)
    return _WHITESPACE.sub(" ", text).strip()


def sanitize_turns(
    turns: object,
    *,
    max_messages: int = _MAX_MESSAGES_DEFAULT,
    max_message_chars: int = _MAX_MESSAGE_CHARS_DEFAULT,
    max_total_chars: int = _MAX_TOTAL_CHARS_DEFAULT,
) -> tuple[tuple[str, str], ...]:
    """Validate and sanitize a chat history, returning clean (role, content) pairs."""
    if isinstance(turns, str | bytes) or not isinstance(turns, tuple | list):
        raise ValueError("turns must be a sequence of (role, content) pairs")
    turns = list(turns)
    if not turns:
        raise ValueError("at least one message is required")
    if len(turns) > max_messages:
        raise ValueError("too many messages")
    roles = {"user", "assistant"}
    for turn in turns:
        if not isinstance(turn, tuple | list) or len(turn) != 2:
            raise ValueError("each turn must be a (role, content) pair")
        role, content = turn
        if role not in roles:
            raise ValueError("role must be 'user' or 'assistant'")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
    if turns[-1][0] != "user":
        raise ValueError("the last message must be from the user")
    cleaned: list[tuple[str, str]] = []
    total = 0
    for role, content in turns:
        text = _clean(content)
        if not text:
            raise ValueError("message content is empty after sanitizing")
        if len(text) > max_message_chars:
            raise ValueError("a message exceeds the length cap")
        total += len(text)
        cleaned.append((role, text))  # type: ignore[arg-type]
    if total > max_total_chars:
        raise ValueError("the messages exceed the total length cap")
    return tuple(cleaned)
