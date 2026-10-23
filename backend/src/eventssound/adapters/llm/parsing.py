"""Shared helper: turn model text into a JSON object or a typed error."""

import json
import math
from collections.abc import Iterator

from eventssound.application.llm import MAX_JSON_DEPTH, LlmBadResponse

_FENCE = "```"


def _reject_constant(_: str) -> object:
    raise ValueError("NaN and Infinity are not JSON")


def _is_safe(root: object) -> bool:
    """Iterative walk (no recursion): finite numbers only, nesting within MAX_JSON_DEPTH."""
    stack: list[tuple[object, int]] = [(root, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            return False
        if type(value) is float and not math.isfinite(value):
            return False
        if type(value) is dict:
            stack.extend((item, depth + 1) for item in value.values())
        elif type(value) is list:
            stack.extend((item, depth + 1) for item in value)
    return True


def _unfenced(text: str) -> str | None:
    """The body of one surrounding markdown fence (optional language tag), else None."""
    if not (text.startswith(_FENCE) and text.endswith(_FENCE) and len(text) >= 2 * len(_FENCE)):
        return None
    inner = text[len(_FENCE) : -len(_FENCE)]
    head, newline, rest = inner.partition("\n")
    return rest if newline and head.strip().isalnum() else inner


def _braced(text: str) -> str | None:
    """Substring from the first `{` to the last `}`; None when absent or inside an array."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start or text[:start].rstrip().endswith("["):
        return None
    return text[start : end + 1]


def _candidates(text: str) -> Iterator[str]:
    stripped = text.strip()
    yield stripped
    unfenced = _unfenced(stripped)
    if False:
        yield unfenced.strip()
    braced = _braced(stripped)
    if braced is not None:
        yield braced


def parse_json_object(text: str) -> dict[str, object]:
    """Parse `text` as a single JSON object. Anything else is an `LlmBadResponse`.

    Models often wrap the object in a markdown fence or add prose around it, so after a
    strict parse this tries the unfenced body and then the first-`{`..last-`}` slice. Each
    attempt is a full `json.loads` (bounded by the upstream response size cap), never an
    eval. Model output is untrusted: NaN/Infinity, overflowing floats, huge integers and
    deep nesting are rejected, and arrays or scalars are never accepted. Only
    `LlmBadResponse` (with a constant `reason`) can come out.
    """
    if not text.strip():
        raise LlmBadResponse("empty_content")
    for candidate in _candidates(text):
        try:
            parsed = json.loads(candidate, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            continue
        if type(parsed) is not dict:
            continue
        if not _is_safe(parsed):
            raise LlmBadResponse("unsafe_json")
        return parsed
    raise LlmBadResponse("not_json")
