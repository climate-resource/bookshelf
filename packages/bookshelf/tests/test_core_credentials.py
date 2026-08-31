"""Tests for the stored-credential store (keychain + 0600 file) harvested from the PoC CLI."""

import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bookshelf._core import credentials

# Captured before the autouse fixture swaps the helpers out, for the degrade test.
_REAL_KEYCHAIN_SET = credentials._keychain_set
_REAL_KEYCHAIN_GET = credentials._keychain_get
_REAL_KEYCHAIN_DELETE = credentials._keychain_delete


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(credentials, "credentials_path", lambda: path)

    # Mock the OS keychain
    store: dict[str, str] = {}

    def fake_set(username: str, value: str) -> bool:
        store[username] = value
        return True

    monkeypatch.setattr(credentials, "_keychain_set", fake_set)
    monkeypatch.setattr(credentials, "_keychain_get", store.get)
    monkeypatch.setattr(credentials, "_keychain_delete", lambda k: store.pop(k, None))
    return path


def test_round_trip_with_file_permissions(isolated_store: Path) -> None:
    expires = datetime(2030, 1, 1, tzinfo=UTC)
    credentials.save_credentials(
        "tok",
        refresh_token="rt",
        expires_at=expires,
        api_url="https://api.test/bookshelf",
    )
    loaded = credentials.load_credentials()
    assert loaded is not None
    assert loaded.access_token == "tok"
    assert loaded.refresh_token == "rt"
    assert loaded.expires_at == expires
    assert loaded.api_url == "https://api.test/bookshelf"
    mode = stat.S_IMODE(isolated_store.stat().st_mode)
    assert mode == 0o600


def test_save_leaves_no_temporary_file_behind(isolated_store: Path) -> None:
    credentials.save_credentials("tok", api_url="https://api.test")
    assert isolated_store.exists()
    assert stat.S_IMODE(isolated_store.stat().st_mode) == 0o600
    leftovers = [
        entry.name for entry in isolated_store.parent.iterdir() if entry.name.endswith(".tmp")
    ]
    assert leftovers == []


def test_second_save_replaces_the_store_without_losing_records(isolated_store: Path) -> None:
    credentials.save_credentials("a", api_url="https://api.test")
    credentials.save_credentials("b", api_url="https://staging.test")

    data = json.loads(isolated_store.read_text())
    assert set(data["records"]) == {
        credentials.record_key("https://api.test", "user"),
        credentials.record_key("https://staging.test", "user"),
    }
    assert stat.S_IMODE(isolated_store.stat().st_mode) == 0o600


def test_existing_store_permissions_are_tightened_before_write(
    isolated_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_store.write_text("{}")
    isolated_store.chmod(0o644)
    original_dump = json.dump
    mode_during_write: list[int] = []

    def capture_mode(*args: object, **kwargs: object) -> None:
        destination = args[1]
        mode_during_write.append(stat.S_IMODE(os.fstat(destination.fileno()).st_mode))
        original_dump(*args, **kwargs)

    monkeypatch.setattr(credentials.json, "dump", capture_mode)
    credentials.save_credentials("tok", api_url="https://api.test")

    assert mode_during_write == [0o600]


def test_keychain_value_wins_over_file_copy(isolated_store: Path) -> None:
    credentials.save_credentials("tok", refresh_token="rt", api_url="https://api.test")
    # Simulate the file copy going stale while the keychain holds the fresh pair.
    data = json.loads(isolated_store.read_text())
    key = credentials.record_key("https://api.test", "user")
    data["records"][key]["access_token"] = "stale"
    isolated_store.write_text(json.dumps(data))
    loaded = credentials.load_credentials()
    assert loaded is not None
    assert loaded.access_token == "tok"


def test_replacing_credentials_clears_optional_secrets() -> None:
    credentials.save_credentials(
        "old-token",
        api_url="https://api.test",
        refresh_token="old-refresh",
        identity_assertion="old-assertion",
    )

    credentials.save_credentials("new-token", api_url="https://api.test")

    loaded = credentials.load_credentials()
    assert loaded is not None
    assert loaded.access_token == "new-token"
    assert loaded.refresh_token is None
    assert loaded.identity_assertion is None


def test_missing_or_corrupt_file_returns_none(isolated_store: Path) -> None:
    assert credentials.load_credentials() is None
    isolated_store.write_text("{not json")
    assert credentials.load_credentials() is None


def test_clear_removes_file_and_keychain(isolated_store: Path) -> None:
    credentials.save_credentials(
        "at", api_url="https://api.test", refresh_token="rt", identity_assertion="ia"
    )
    key = credentials.record_key("https://api.test", "user")
    credentials.clear_credentials()
    assert not isolated_store.exists()
    assert credentials.load_credentials() is None
    for field in credentials._SECRET_FIELDS:
        assert credentials._keychain_get(f"{key}:{field}") is None


def test_expiry_derived_from_jwt_exp_when_absent(isolated_store: Path) -> None:
    from tests.test_core_auth import jwt_with_exp

    token = jwt_with_exp(1893456000)
    credentials.save_credentials(token, api_url="https://api.test")
    loaded = credentials.load_credentials()
    assert loaded is not None
    assert loaded.expires_at == datetime.fromtimestamp(1893456000, tz=UTC)


def test_records_coexist_per_deployment_and_kind(isolated_store: Path) -> None:
    credentials.save_credentials(
        "user-prod", refresh_token="rt", api_url="https://api.test", subject="me@test.com"
    )
    credentials.save_credentials(
        "agent-prod",
        api_url="https://api.test",
        kind="agent",
        identity_assertion="ia-prod",
        subject="agent:1",
        claimed=False,
    )
    credentials.save_credentials(
        "user-staging", api_url="https://staging.test", subject="me@test.com"
    )

    assert len(credentials.list_credentials()) == 3
    # The agent login did not destroy the user login on the same deployment.
    subjects = {(c.api_url, c.kind) for c in credentials.list_credentials()}
    assert subjects == {
        ("https://api.test", "user"),
        ("https://api.test", "agent"),
        ("https://staging.test", "user"),
    }
    # The last save per deployment is the active one.
    assert credentials.active_kinds() == {
        "https://api.test": "agent",
        "https://staging.test": "user",
    }
    loaded = credentials.load_credentials("https://api.test")
    assert loaded is not None
    assert loaded.access_token == "agent-prod"
    # The default deployment follows the most recent save.
    default = credentials.load_credentials()
    assert default is not None
    assert default.api_url == "https://staging.test"


def test_set_active_switches_without_reauthentication(isolated_store: Path) -> None:
    credentials.save_credentials("user-tok", api_url="https://api.test", subject="me@test.com")
    credentials.save_credentials(
        "agent-tok",
        api_url="https://api.test",
        kind="agent",
        identity_assertion="ia",
        subject="agent:1",
    )
    switched = credentials.set_active("https://api.test", "user")
    assert switched.access_token == "user-tok"
    loaded = credentials.load_credentials("https://api.test")
    assert loaded is not None
    assert loaded.kind == "user"
    with pytest.raises(KeyError):
        credentials.set_active("https://api.test", "missing")


def test_assertion_and_its_separate_expiry_survive_a_round_trip(isolated_store: Path) -> None:
    token_expires = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    assertion_expires = datetime(2030, 1, 31, 12, 0, tzinfo=UTC)
    credentials.save_credentials(
        "bsat_tok",
        api_url="https://api.test",
        kind="agent",
        expires_at=token_expires,
        identity_assertion="ia_secret",
        assertion_expires_at=assertion_expires,
        subject="agent:1",
        claimed=True,
    )
    loaded = credentials.load_credentials("https://api.test")
    assert loaded is not None
    assert loaded.identity_assertion == "ia_secret"
    assert loaded.expires_at == token_expires
    assert loaded.assertion_expires_at == assertion_expires
    assert loaded.claimed is True


def test_clear_one_deployment_leaves_the_others(isolated_store: Path) -> None:
    credentials.save_credentials("a", api_url="https://api.test")
    credentials.save_credentials("b", api_url="https://staging.test")
    credentials.clear_credentials("https://staging.test")
    assert credentials.load_credentials("https://staging.test") is None
    remaining = credentials.load_credentials("https://api.test")
    assert remaining is not None
    # The default deployment moved off the cleared one.
    assert credentials.load_credentials() is not None


def test_working_keychain_keeps_every_secret_out_of_the_file(isolated_store: Path) -> None:
    credentials.save_credentials(
        "at",
        api_url="https://api.test",
        refresh_token="rt",
        identity_assertion="ia",
    )

    raw = isolated_store.read_text()
    for secret in ("at", "rt", "ia"):
        assert f'"{secret}"' not in raw

    loaded = credentials.load_credentials()
    assert loaded is not None
    assert loaded.access_token == "at"
    assert loaded.refresh_token == "rt"
    assert loaded.identity_assertion == "ia"


def test_absent_backend_falls_back_to_the_file_copy(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no keychain to hold them the secrets must still be persisted."""

    class BrokenKeyring:
        def set_password(self, *args: object) -> None:
            raise RuntimeError("no keychain backend")

        def get_password(self, *args: object) -> str:
            raise RuntimeError("no keychain backend")

    import sys

    monkeypatch.setattr(credentials, "_keychain_set", _REAL_KEYCHAIN_SET)
    monkeypatch.setattr(credentials, "_keychain_get", _REAL_KEYCHAIN_GET)
    monkeypatch.setitem(sys.modules, "keyring", BrokenKeyring())
    credentials.save_credentials(
        "at", api_url="https://api.test", refresh_token="rt", identity_assertion="ia"
    )

    key = credentials.record_key("https://api.test", "user")
    record = json.loads(isolated_store.read_text())["records"][key]
    assert record["access_token"] == "at"
    assert record["refresh_token"] == "rt"
    assert record["identity_assertion"] == "ia"

    loaded = credentials.load_credentials()
    assert loaded is not None
    assert loaded.access_token == "at"
    assert loaded.refresh_token == "rt"
    assert loaded.identity_assertion == "ia"


def test_backend_that_cannot_serve_a_write_falls_back_to_the_file_copy(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write the backend accepts but cannot read back must not lose the secret."""

    class LyingKeyring:
        def set_password(self, *args: object) -> None:
            return None

        def get_password(self, *args: object) -> str | None:
            return None

    import sys

    monkeypatch.setattr(credentials, "_keychain_set", _REAL_KEYCHAIN_SET)
    monkeypatch.setattr(credentials, "_keychain_get", _REAL_KEYCHAIN_GET)
    monkeypatch.setitem(sys.modules, "keyring", LyingKeyring())
    credentials.save_credentials(
        "at", api_url="https://api.test", refresh_token="rt", identity_assertion="ia"
    )

    key = credentials.record_key("https://api.test", "user")
    record = json.loads(isolated_store.read_text())["records"][key]
    assert record["access_token"] == "at"
    assert record["refresh_token"] == "rt"
    assert record["identity_assertion"] == "ia"

    loaded = credentials.load_credentials()
    assert loaded is not None
    assert loaded.access_token == "at"


def test_keychain_failure_degrades_to_file(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken keyring backend must never break login, load, or logout."""

    class BrokenKeyring:
        def set_password(self, *args: object) -> None:
            raise RuntimeError("no keychain backend")

        def get_password(self, *args: object) -> str:
            raise RuntimeError("no keychain backend")

    import sys

    monkeypatch.setattr(credentials, "_keychain_set", _REAL_KEYCHAIN_SET)
    monkeypatch.setattr(credentials, "_keychain_get", _REAL_KEYCHAIN_GET)
    monkeypatch.setitem(sys.modules, "keyring", BrokenKeyring())
    credentials.save_credentials("tok", refresh_token="rt", api_url="https://api.test")
    loaded = credentials.load_credentials()
    assert loaded is not None
    assert loaded.access_token == "tok"


class _SpyKeyring:
    """A keyring backend that records every call it is asked to make."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.store: dict[str, str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append("get_password")
        return self.store.get(username)

    def set_password(self, service: str, username: str, value: str) -> None:
        self.calls.append("set_password")
        self.store[username] = value

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append("delete_password")
        self.store.pop(username, None)


@pytest.fixture
def spy_keyring(monkeypatch: pytest.MonkeyPatch) -> _SpyKeyring:
    """Restore the real keychain helpers over a recording backend."""
    spy = _SpyKeyring()
    monkeypatch.setattr(credentials, "_keychain_set", _REAL_KEYCHAIN_SET)
    monkeypatch.setattr(credentials, "_keychain_get", _REAL_KEYCHAIN_GET)
    monkeypatch.setattr(credentials, "_keychain_delete", _REAL_KEYCHAIN_DELETE)
    monkeypatch.setitem(sys.modules, "keyring", spy)
    return spy


@pytest.mark.parametrize("value", ["1", "true", "yes", "anything"])
def test_use_keychain_flag_is_read_from_the_environment(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_USE_KEYCHAIN", value)
    assert credentials.keychain_enabled()


@pytest.mark.parametrize("value", ["", "0", "false", "no", "  "])
def test_use_keychain_flag_stays_off_for_falsey_values(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_USE_KEYCHAIN", value)
    assert not credentials.keychain_enabled()


def test_the_keychain_is_off_unless_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOKSHELF_USE_KEYCHAIN", raising=False)
    assert not credentials.keychain_enabled()


def test_secrets_stay_in_the_file_by_default(
    isolated_store: Path, spy_keyring: _SpyKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """By default the secrets round-trip through the file, untouched by the keychain."""
    monkeypatch.delenv("BOOKSHELF_USE_KEYCHAIN", raising=False)

    credentials.save_credentials(
        "at",
        api_url="https://api.test",
        refresh_token="rt",
        identity_assertion="ia",
    )
    loaded = credentials.load_credentials()

    assert loaded is not None
    assert (loaded.access_token, loaded.refresh_token, loaded.identity_assertion) == (
        "at",
        "rt",
        "ia",
    )
    record = json.loads(isolated_store.read_text())["records"]["https://api.test|user"]
    assert record["access_token"] == "at"
    assert "get_password" not in spy_keyring.calls
    assert "set_password" not in spy_keyring.calls


def test_opting_in_moves_the_secrets_to_the_keychain(
    isolated_store: Path, spy_keyring: _SpyKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOOKSHELF_USE_KEYCHAIN", "1")

    credentials.save_credentials("at", api_url="https://api.test", refresh_token="rt")

    record = json.loads(isolated_store.read_text())["records"]["https://api.test|user"]
    assert record["access_token"] is None
    assert spy_keyring.store["https://api.test|user:access_token"] == "at"
    loaded = credentials.load_credentials()
    assert loaded is not None
    assert loaded.access_token == "at"


def test_logout_still_clears_the_keychain_when_it_is_off(
    isolated_store: Path, spy_keyring: _SpyKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A secret an earlier run left in the keychain must not survive a logout."""
    monkeypatch.setenv("BOOKSHELF_USE_KEYCHAIN", "1")
    credentials.save_credentials("at", api_url="https://api.test")
    assert spy_keyring.store

    monkeypatch.delenv("BOOKSHELF_USE_KEYCHAIN", raising=False)
    credentials.clear_credentials()

    assert spy_keyring.store == {}


def test_a_keychain_only_login_is_reported_as_stranded(
    isolated_store: Path, spy_keyring: _SpyKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record written under the old default must be nameable, so the CLI can explain it."""
    monkeypatch.setenv("BOOKSHELF_USE_KEYCHAIN", "1")
    credentials.save_credentials("at", api_url="https://api.test")
    assert credentials.keychain_only_records() == []

    monkeypatch.delenv("BOOKSHELF_USE_KEYCHAIN", raising=False)
    assert credentials.load_credentials() is None
    assert credentials.keychain_only_records() == ["https://api.test"]
