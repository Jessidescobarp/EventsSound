"""A minimal secret wrapper: the value never shows up in repr, str, format, pickles or copies."""

import re

_MASK = "Secret('**********')"
_KEY = re.compile(r"[\x21-\x7e]{1,512}")


class SecretError(ValueError):
    """The secret is unusable. The message never contains the offending value."""


class Secret:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not _KEY.fullmatch(value):
            raise SecretError("secret must be 1..512 printable ASCII characters without spaces")
        object.__setattr__(self, "_value", value)

    @classmethod
    def wrap(cls, value: object) -> "Secret":
        """Accept a Secret, a plain string or a SecretStr-like object (`get_secret_value()`)."""
        if isinstance(value, Secret):
            return value
        getter = getattr(value, "get_secret_value", None)
        return cls(getter() if callable(getter) else value)  # type: ignore[arg-type]

    def get_secret_value(self) -> str:
        return self._value  # type: ignore[no-any-return]

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Secret is immutable")

    def __repr__(self) -> str:
        return _MASK

    def __str__(self) -> str:
        return _MASK

    def __format__(self, format_spec: str) -> str:
        return format(_MASK, format_spec)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __reduce__(self) -> str | tuple[object, ...]:
        raise TypeError("Secret cannot be pickled or copied")
