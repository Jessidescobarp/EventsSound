"""Argon2id password hashing behind the `PasswordHasher` port.

Library defaults are the OWASP-recommended minimum for argon2id (19 MiB, 2 passes). Each
verification holds that memory, so at most `max_concurrent` run at once: a login burst queues
instead of exhausting the 512 MB Render instance.
"""

import threading

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2Hasher:
    def __init__(self, max_concurrent: int = 3) -> None:
        self._hasher = PasswordHasher()
        self._slots = threading.BoundedSemaphore(max_concurrent)

    def hash(self, password: str) -> str:
        with self._slots:
            return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            with self._slots:
                return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False
