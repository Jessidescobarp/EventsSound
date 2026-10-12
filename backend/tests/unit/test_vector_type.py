"""VectorType: a thin pgvector column type with no dependency on the `pgvector` package."""

import math

import pytest
from sqlalchemy.dialects import postgresql

from eventssound.adapters.db.vector import VectorType, format_vector, parse_vector

DIALECT = postgresql.dialect()


def test_column_spec_carries_the_dimension() -> None:
    assert VectorType(1024).get_col_spec() == "vector(1024)"
    assert VectorType(3).get_col_spec() == "vector(3)"


@pytest.mark.parametrize("dimensions", [0, -1, 2001, True, 1.5, "3", None])
def test_invalid_dimensions_are_rejected(dimensions: object) -> None:
    with pytest.raises(ValueError):
        VectorType(dimensions)  # type: ignore[arg-type]


def test_the_boundary_dimensions_are_accepted() -> None:
    assert VectorType(1).get_col_spec() == "vector(1)"
    assert VectorType(2000).get_col_spec() == "vector(2000)"


def test_format_is_a_bracketed_comma_list_with_full_precision() -> None:
    assert format_vector((0.5, -1.0, 0.1), 3) == "[0.5,-1,0.1]"
    assert format_vector([1, 2], 2) == "[1,2]"
    # 8 significant digits keep float32 round trips stable
    assert float(format_vector((1 / 3,), 1).strip("[]")) == pytest.approx(1 / 3, rel=1e-7)


@pytest.mark.parametrize(
    "value",
    [
        (1.0, 2.0),  # wrong length
        (1.0, 2.0, 3.0, 4.0),
        (),
        (1.0, math.nan, 0.0),
        (1.0, math.inf, 0.0),
        (1.0, -math.inf, 0.0),
        ("1", "2", "3"),
        (True, 0.0, 0.0),
        "[1,2,3]",
        b"123",
        None,
        5,
        (1e39, 0.0, 0.0),  # float32 overflow
    ],
    ids=["short", "long", "empty", "nan", "inf", "-inf", "strings", "bool", "str", "bytes",
         "none", "int", "float32-overflow"],
)  # fmt: skip
def test_invalid_vectors_are_rejected_before_reaching_the_database(value: object) -> None:
    with pytest.raises(ValueError):
        format_vector(value, 3)  # type: ignore[arg-type]


def test_the_all_zero_vector_is_rejected() -> None:
    # cosine distance of a zero vector is NaN in pgvector
    with pytest.raises(ValueError):
        format_vector((0.0, 0.0, 0.0), 3)


def test_parse_reads_what_postgres_prints() -> None:
    assert parse_vector("[1,2.5,-3]") == (1.0, 2.5, -3.0)
    assert parse_vector("[0.1]") == (0.1,)


@pytest.mark.parametrize("text", ["", "1,2", "[1,2", "[a,b]", "[]", "[1,,2]", "[nan]"])
def test_parse_rejects_malformed_text(text: str) -> None:
    with pytest.raises(ValueError):
        parse_vector(text)


def test_bind_and_result_processors_round_trip() -> None:
    column = VectorType(3)
    bind = column.bind_processor(DIALECT)
    result = column.result_processor(DIALECT, None)

    assert bind((0.25, 0.5, -0.5)) == "[0.25,0.5,-0.5]"
    assert bind(None) is None
    assert result("[0.25,0.5,-0.5]") == (0.25, 0.5, -0.5)
    assert result(None) is None


def test_reflection_resolves_the_vector_type_name() -> None:
    assert postgresql.base.ischema_names["vector"] is VectorType


def test_equal_dimensions_compare_equal_for_drift_detection() -> None:
    assert VectorType(4) == VectorType(4)
    assert VectorType(4) != VectorType(5)
