"""Validation of the `Extraction` model: the only data that survives `understand`."""

import pytest
from pydantic import ValidationError

from eventssound.adapters.agent.schemas import Extraction

VALID = {
    "intent": "quote",
    "event_type": "wedding",
    "event_date": "2026-10-17",
    "start_time": "20:00",
    "end_time": "23:30",
    "duration_hours": None,
    "end_date": None,
    "guest_count": 150,
    "distance_km": 45,
    "locality": None,
    "venue": "outdoor",
    "items": [{"mention": "parlantes", "quantity": 2}],
    "needs": [],
}


def make(**overrides):
    data = {**VALID, **overrides}
    return Extraction.model_validate(data)


class TestHappyPath:
    def test_full_extraction_validates(self) -> None:
        extraction = make()
        assert extraction.intent == "quote"
        assert extraction.event_date == "2026-10-17"
        assert extraction.items[0].mention == "parlantes"
        assert extraction.items[0].quantity == 2

    def test_all_nulls_with_other_intent_is_valid(self) -> None:
        assert Extraction.model_validate({"intent": "other"}).intent == "other"

    def test_defaults_for_omitted_fields(self) -> None:
        extraction = Extraction.model_validate({"intent": "quote"})
        assert extraction.event_date is None
        assert extraction.items == []
        assert extraction.needs == []


class TestBounds:
    @pytest.mark.parametrize("value", ["2026-1-7", "26-10-17", "17/10/2026", "2026-10-17T20:00"])
    def test_event_date_must_be_iso_date(self, value: str) -> None:
        with pytest.raises(ValidationError):
            make(event_date=value)

    @pytest.mark.parametrize("value", ["2026-02-30", "2026-13-01", "2026-00-10"])
    def test_event_date_must_be_a_real_date(self, value: str) -> None:
        with pytest.raises(ValidationError):
            make(event_date=value)

    @pytest.mark.parametrize("value", ["24:00", "8:00", "20:5", "2000", "20:00:00"])
    def test_start_time_must_be_hh_mm(self, value: str) -> None:
        with pytest.raises(ValidationError):
            make(start_time=value)

    @pytest.mark.parametrize("value", [0.1, 0, 72.5, 100, -1])
    def test_duration_hours_bounds(self, value: float) -> None:
        with pytest.raises(ValidationError):
            make(duration_hours=value)

    @pytest.mark.parametrize(
        "key,low,high", [("guest_count", 1, 100_000), ("distance_km", 0, 5_000)]
    )
    def test_integer_bounds(self, key: str, low: int, high: int) -> None:
        with pytest.raises(ValidationError):
            make(**{key: low - 1})
        with pytest.raises(ValidationError):
            make(**{key: high + 1})

    def test_quantity_bounds(self) -> None:
        with pytest.raises(ValidationError):
            make(items=[{"mention": "parlantes", "quantity": 0}])
        with pytest.raises(ValidationError):
            make(items=[{"mention": "parlantes", "quantity": 10_001}])

    def test_max_eight_items_and_needs(self) -> None:
        items = [{"mention": f"item {i}", "quantity": 1} for i in range(9)]
        with pytest.raises(ValidationError):
            make(items=items)
        with pytest.raises(ValidationError):
            make(needs=[f"necesidad {i}" for i in range(9)])

    def test_mention_and_locality_max_length(self) -> None:
        with pytest.raises(ValidationError):
            make(items=[{"mention": "x" * 81, "quantity": 1}])
        with pytest.raises(ValidationError):
            make(locality="a" * 61)
        with pytest.raises(ValidationError):
            make(needs=["n" * 61])


class TestCharset:
    @pytest.mark.parametrize(
        "hostile",
        ["<script>", "parlantes\\n", "parl\u00e1ntes\U0001f3b2", "back\\slash", "parlantes\ttab"],
    )
    def test_restricted_charset_is_enforced(self, hostile: str) -> None:
        with pytest.raises(ValidationError):
            make(items=[{"mention": hostile, "quantity": 1}])

    @pytest.mark.parametrize("allowed", ["parlantes 15", "Mezcladora-16", "cafe, con leche"])
    def test_allowed_characters_pass(self, allowed: str) -> None:
        extraction = make(items=[{"mention": allowed, "quantity": 1}])
        assert extraction.items[0].mention == allowed


class TestStrictness:
    def test_extra_fields_are_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            make(unit_price=100)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("intent", "chit-chat"),
            ("intent", "quote,"),  # an unanchored pattern would accept a superstring
            ("intent", "xquotex"),
            ("event_type", "funeral"),
            ("event_type", "weddingXYZ"),
            ("venue", "underground"),
            ("venue", "outdoors-and-more"),
        ],
    )
    def test_enum_fields_are_closed_sets(self, field: str, value: str) -> None:
        with pytest.raises(ValidationError):
            make(**{field: value})

    def test_json_schema_exposes_closed_enums_to_the_model(self) -> None:
        # The provider constrains decoding with this schema: an unanchored `pattern` let the
        # model keep writing after `quote` and emit `"quote,` (broken JSON).
        props = Extraction.model_json_schema()["properties"]
        assert props["intent"]["enum"] == ["quote", "other"]
        assert {"enum": ["indoor", "outdoor"], "type": "string"} in props["venue"]["anyOf"]
        assert "pattern" not in props["intent"]

    def test_json_schema_requires_every_field_so_the_model_cannot_skip_one(self) -> None:
        schema = Extraction.model_json_schema()
        assert sorted(schema["required"]) == sorted(schema["properties"])
        # ...while validation still accepts an omitted optional field (defaults apply).
        assert make().event_type == "wedding"
        data = {"intent": "other"}
        assert Extraction.model_validate(data).items == []

    def test_strings_are_not_coerced_from_numbers(self) -> None:
        with pytest.raises(ValidationError):
            make(event_date=20261017)

    def test_quantity_is_not_coerced_from_string(self) -> None:
        with pytest.raises(ValidationError):
            make(items=[{"mention": "parlantes", "quantity": "2"}])
