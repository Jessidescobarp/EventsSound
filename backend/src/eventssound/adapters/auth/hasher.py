"""Argon2id password hashing behind the `PasswordHasher` port.

Library defaults are the OWASP-recommended minimum for argon2id (19 MiB, 2 passes), which keeps
a login light enough for the 512 MB Render instance.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2Hasher:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False
