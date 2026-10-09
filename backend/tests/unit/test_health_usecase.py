from eventssound.application.health import check_database


class HealthyDatabase:
    def ping(self) -> None:
        return None


class BrokenDatabase:
    def ping(self) -> None:
        raise ConnectionError("secret-host unreachable")


def test_check_database_is_true_when_ping_succeeds() -> None:
    assert check_database(HealthyDatabase()) is True


def test_check_database_is_false_when_ping_fails() -> None:
    assert check_database(BrokenDatabase()) is False
