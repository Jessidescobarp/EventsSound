"""Application-level errors raised by repository adapters."""


class RepositoryUnavailable(Exception):
    """The storage could not be reached or failed. The message never carries connection details."""


class ConnectionFailed(RepositoryUnavailable):
    """The database could not be reached (network, refusal, timeout, shutdown)."""


class AuthenticationFailed(RepositoryUnavailable):
    """The database rejected the credentials or the client."""


class SchemaNotReady(RepositoryUnavailable):
    """The tables are missing or the migration revision is not the one the code expects."""


class InvalidStoredData(Exception):
    """A stored row violates the domain contract (the caller is not at fault: not a DomainError)."""
