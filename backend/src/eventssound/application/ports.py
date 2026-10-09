from typing import Protocol


class DatabaseHealthPort(Protocol):
    def ping(self) -> None:
        """Return normally when the database answers; raise otherwise."""
        ...
