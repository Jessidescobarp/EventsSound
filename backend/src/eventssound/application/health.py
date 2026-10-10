from eventssound.application.ports import DatabaseHealthPort


def check_database(database: DatabaseHealthPort) -> bool:
    """Readiness use case: True when the database answers, False otherwise."""
    try:
        database.ping()
    except Exception:
        return False
    return True
