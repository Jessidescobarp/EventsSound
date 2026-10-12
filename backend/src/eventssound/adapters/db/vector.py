"""A thin pgvector column type, written by hand to avoid the `pgvector` package and numpy.

psycopg 3 sends a Python `str` as an untyped text literal, so the value `'[0.1,0.2]'` is cast to
`vector` by the server (the column type on INSERT, `CAST(:q AS vector)` in queries). No
per-connection adapter registration is needed. Only the cosine operator `<=>` is used, written in
SQL by the store.
"""

import math
import re
import struct
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

MAX_DIMENSIONS = 2_000  # pgvector's limit for indexed vectors; also the provider-side bound
_FLOAT32_MAX = struct.unpack("f", struct.pack("I", 0x7F7FFFFF))[0]
# pgvector's float32 cosine math overflows or underflows outside this range (probed): the
# largest component must lie within it, so zero and near-zero vectors are rejected too.
_MIN_MAGNITUDE, _MAX_MAGNITUDE = 1e-18, 1e18
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def format_vector(value: object, dimensions: int) -> str:
    """The pgvector text literal of `value`. Raises ValueError for anything the database would
    reject or mis-handle: wrong length, non-numbers, bools, NaN, infinities, float32 overflow and
    vectors whose largest component is outside 1e-18..1e18 (pgvector's cosine
    math breaks there, and the zero vector has a NaN distance)."""
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ValueError("a vector must be a sequence of numbers")
    if len(value) != dimensions:
        raise ValueError(f"a vector must have exactly {dimensions} components")
    parts = []
    for component in value:
        if type(component) not in (int, float):
            raise ValueError("vector components must be int or float")
        try:
            number = float(component)
        except OverflowError:
            raise ValueError("vector components must be finite float32 values") from None
        if not math.isfinite(number) or abs(number) > _FLOAT32_MAX:
            raise ValueError("vector components must be finite float32 values")
        parts.append(format(number, ".8g"))
    largest = max(abs(float(part)) for part in parts)
    if not _MIN_MAGNITUDE <= largest <= _MAX_MAGNITUDE:
        raise ValueError("the largest component must be within 1e-18..1e18 (no zero vectors)")
    return "[" + ",".join(parts) + "]"


def parse_vector(text: str) -> tuple[float, ...]:
    """Read pgvector's text output, e.g. `[1,2.5,-3]`."""
    if not isinstance(text, str) or not (text.startswith("[") and text.endswith("]")):
        raise ValueError("not a vector literal")
    pieces = text[1:-1].split(",")
    if not all(_NUMBER.fullmatch(piece) for piece in pieces):
        raise ValueError("not a vector literal")
    return tuple(float(piece) for piece in pieces)


class VectorType(UserDefinedType[Any]):
    """`vector(N)` column. Python values are tuples of floats."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        if type(dimensions) is not int or not 1 <= dimensions <= MAX_DIMENSIONS:
            raise ValueError(f"dimensions must be an int within 1..{MAX_DIMENSIONS}")
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect: object) -> Callable[[Any], str | None]:
        def process(value: Any) -> str | None:
            return None if value is None else format_vector(value, self.dimensions)

        return process

    def result_processor(self, dialect: object, coltype: object) -> Callable[[Any], Any]:
        def process(value: Any) -> tuple[float, ...] | None:
            return None if value is None else parse_vector(value)

        return process

    def __eq__(self, other: object) -> bool:
        return isinstance(other, VectorType) and other.dimensions == self.dimensions

    def __hash__(self) -> int:
        return hash(("vector", self.dimensions))


# Reflection (Alembic drift checks) resolves the `vector` type name to this class.
postgresql.base.ischema_names["vector"] = VectorType
