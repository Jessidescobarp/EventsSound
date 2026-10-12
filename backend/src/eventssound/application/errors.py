"""Application-level errors raised by repository adapters."""


class RepositoryUnavailable(Exception):
    """The storage could not be reached or failed. The message never carries connection details."""


class InvalidStoredData(Exception):
    """A stored row violates the domain contract (the caller is not at fault: not a DomainError)."""
