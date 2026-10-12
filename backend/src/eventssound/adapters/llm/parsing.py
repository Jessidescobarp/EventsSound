"""Shared helper: turn model text into a JSON object or a typed error."""

import json
import math

from eventssound.application.llm import MAX_JSON_DEPTH, LlmBadResponse


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


def parse_json_object(text: str) -> dict[str, object]:
    """Parse `text` as a single JSON object. Anything else is an `LlmBadResponse`.

    Model output is untrusted: NaN/Infinity, overflowing floats, huge integers and deep
    nesting are all rejected here so only `LlmBadResponse` can come out.
    """
    try:
        parsed = json.loads(text.strip(), parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise LlmBadResponse() from None
    if type(parsed) is not dict or not _is_safe(parsed):
        raise LlmBadResponse()
    return parsed
