"""Portfolio events: illustrative past events shown on the public page. Stdlib only."""

from dataclasses import dataclass

from .errors import InvalidPortfolioEvent

MAX_TITLE = 120  # VARCHAR(120) in the database
MAX_KIND = 40
MAX_DESCRIPTION = 500
MAX_EQUIPMENT = 12
MAX_EQUIPMENT_NAME = 80


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise InvalidPortfolioEvent(f"{name} must be text")
    text = value.strip()
    if not 1 <= len(text) <= limit:
        raise InvalidPortfolioEvent(f"{name} must have 1 to {limit} characters")
    if not text.isprintable():  # it reaches pages and, later, prompts: no control characters
        raise InvalidPortfolioEvent(f"{name} must not contain control characters")
    return text


@dataclass(frozen=True, slots=True)
class PortfolioEvent:
    title: str
    kind: str
    description: str
    equipment: tuple[str, ...]
    visible: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _text(self.title, "title", MAX_TITLE))
        object.__setattr__(self, "kind", _text(self.kind, "kind", MAX_KIND))
        object.__setattr__(
            self, "description", _text(self.description, "description", MAX_DESCRIPTION)
        )
        if isinstance(self.equipment, str) or len(tuple(self.equipment)) > MAX_EQUIPMENT:
            raise InvalidPortfolioEvent(f"equipment must be a list of at most {MAX_EQUIPMENT}")
        object.__setattr__(
            self,
            "equipment",
            tuple(_text(name, "equipment name", MAX_EQUIPMENT_NAME) for name in self.equipment),
        )
        if type(self.visible) is not bool:
            raise InvalidPortfolioEvent("visible must be a bool")
