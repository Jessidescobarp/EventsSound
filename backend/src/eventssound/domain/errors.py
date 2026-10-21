"""Domain errors. Every rule violation raised by the domain derives from DomainError."""


class DomainError(Exception):
    """Base class for all domain rule violations."""


class InvalidMoney(DomainError):
    """A monetary value or a money operation argument is invalid."""


class CurrencyMismatch(DomainError):
    """Two Money values of different currencies were combined or compared."""


class InvalidRules(DomainError):
    """A pricing or availability rule set is inconsistent."""


class InvalidEventRequest(DomainError):
    """An event request violates its bounds."""


class UnknownCatalogEntry(DomainError):
    """A code does not exist in the catalog."""

    def __init__(self, code: str) -> None:
        super().__init__(f"unknown catalog entry: {code}")
        self.code = code


class InvalidQuote(DomainError):
    """A quote or quote line is inconsistent."""


class InvalidAvailability(DomainError):
    """A booking or an availability query is malformed."""


class InvalidCatalog(DomainError):
    """A catalog entity or the catalog as a whole is inconsistent."""


class InvalidPortfolioEvent(DomainError):
    """A portfolio event violates its bounds."""


class InvalidAgentConfig(DomainError):
    """An agent configuration violates its bounds. The message never carries the offending value."""
