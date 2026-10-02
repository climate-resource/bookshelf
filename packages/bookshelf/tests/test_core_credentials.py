"""Tests for the credential store, run against both adapters where the rules are shared."""

import json
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from filelock import FileLock

from bookshelf import AuthConfigurationError, BookshelfError
from bookshelf._core import credentials
from bookshelf._core.credentials import (
    CredentialKind,
    CredentialStore,
    FileCredentialStore,
    MemoryCredentialStore,
    StoredCredentials,
)

API = "https://api.test"
STAGING = "https://staging.test"


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "credentials.json"


@pytest.fixture(params=["file", "memory"])
def store(request: pytest.FixtureRequest, path: Path) -> CredentialStore:
    return FileCredentialStore(path) if request.param == "file" else MemoryCredentialStore()


def login(
    store: CredentialStore, token: str, api_url: str = API, **fields: object
) -> StoredCredentials:
    return store.save_login(StoredCredentials(access_token=token, api_url=api_url, **fields))  # type: ignore[arg-type]


def test_round_trip(store: CredentialStore) -> None:
    expires = datetime(2030, 1, 1, tzinfo=UTC)
    login(store, "tok", f"{API}/bookshelf", refresh_token="rt", expires_at=expires)

    loaded = store.load()

    assert loaded is not None
    assert loaded.access_token == "tok"
    assert loaded.refresh_token == "rt"
    assert loaded.expires_at == expires
    assert loaded.api_url == f"{API}/bookshelf"


def test_a_new_login_replaces_the_optional_secrets(store: CredentialStore) -> None:
    login(store, "old-token", refresh_token="old-refresh", identity_assertion="old-assertion")
    login(store, "new-token")

    loaded = store.load()

    assert loaded is not None
    assert loaded.access_token == "new-token"
    assert loaded.refresh_token is None
    assert loaded.identity_assertion is None


def test_expiry_derived_from_jwt_exp_when_absent(store: CredentialStore) -> None:
    from tests.test_core_auth import jwt_with_exp

    login(store, jwt_with_exp(1893456000))

    loaded = store.load()
    assert loaded is not None
    assert loaded.expires_at == datetime.fromtimestamp(1893456000, tz=UTC)


def test_records_coexist_per_deployment_and_kind(store: CredentialStore) -> None:
    login(store, "user-prod", refresh_token="rt", subject="me@test.com")
    login(
        store,
        "agent-prod",
        kind=CredentialKind.AGENT,
        identity_assertion="ia-prod",
        subject="agent:1",
        claimed=False,
    )
    login(store, "user-staging", STAGING, subject="me@test.com")

    assert {(c.api_url, c.kind) for c in store.records()} == {
        (API, CredentialKind.USER),
        (API, CredentialKind.AGENT),
        (STAGING, CredentialKind.USER),
    }
    # The last save per deployment is the active one.
    assert store.active_kinds() == {API: CredentialKind.AGENT, STAGING: CredentialKind.USER}
    loaded = store.load(API)
    assert loaded is not None
    assert loaded.access_token == "agent-prod"
    # The default deployment follows the most recent login.
    default = store.load()
    assert default is not None
    assert default.api_url == STAGING


def test_set_active_switches_without_reauthentication(store: CredentialStore) -> None:
    login(store, "user-tok", subject="me@test.com")
    login(store, "agent-tok", kind=CredentialKind.AGENT, identity_assertion="ia", subject="agent:1")

    switched = store.set_active(API, CredentialKind.USER)

    assert switched.access_token == "user-tok"
    loaded = store.load(API)
    assert loaded is not None
    assert loaded.kind is CredentialKind.USER
    with pytest.raises(KeyError):
        store.set_active(STAGING, CredentialKind.USER)


def test_assertion_and_its_separate_expiry_survive_a_round_trip(store: CredentialStore) -> None:
    token_expires = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    assertion_expires = datetime(2030, 1, 31, 12, 0, tzinfo=UTC)
    login(
        store,
        "bsat_tok",
        kind=CredentialKind.AGENT,
        expires_at=token_expires,
        identity_assertion="ia_secret",
        assertion_expires_at=assertion_expires,
        subject="agent:1",
        claimed=True,
    )

    loaded = store.load(API)

    assert loaded is not None
    assert loaded.identity_assertion == "ia_secret"
    assert loaded.expires_at == token_expires
    assert loaded.assertion_expires_at == assertion_expires
    assert loaded.claimed is True


def test_clear_one_deployment_leaves_the_others(store: CredentialStore) -> None:
    login(store, "a")
    login(store, "b", STAGING)

    store.clear(STAGING)

    assert store.load(STAGING) is None
    assert store.load(API) is not None
    # The default deployment moved off the cleared one.
    assert store.load() is not None


def test_clear_everything(store: CredentialStore) -> None:
    login(store, "a", refresh_token="rt", identity_assertion="ia")

    store.clear()

    assert store.load() is None
    assert store.records() == []


def test_rotation_replaces_the_secrets_and_keeps_the_default(store: CredentialStore) -> None:
    staging = login(store, "staging-tok", STAGING, refresh_token="rt-1", subject="me@test.com")
    login(store, "prod-tok", refresh_token="rt-prod")

    store.rotate(
        staging, staging.with_token("staging-tok-2", expires_at=None, refresh_token="rt-2")
    )

    rotated = store.load(STAGING)
    assert rotated is not None
    assert rotated.access_token == "staging-tok-2"
    assert rotated.refresh_token == "rt-2"
    assert rotated.subject == "me@test.com"
    # Refreshing a staging client does not make staging the default deployment.
    default = store.load()
    assert default is not None
    assert default.api_url == API


def test_rotation_keeps_a_switched_identity_inactive(store: CredentialStore) -> None:
    user = login(store, "user-tok", refresh_token="rt-1")
    login(store, "agent-tok", kind=CredentialKind.AGENT, identity_assertion="ia")

    store.rotate(user, user.with_token("user-tok-2", expires_at=None, refresh_token="rt-2"))

    assert store.active_kinds() == {API: CredentialKind.AGENT}


def test_rotation_does_not_bring_back_a_logged_out_login(store: CredentialStore) -> None:
    record = login(store, "tok", refresh_token="rt-1")
    store.clear(API)

    store.rotate(record, record.with_token("tok-2", expires_at=None, refresh_token="rt-2"))

    assert store.records() == []


def test_rotation_does_not_overwrite_a_newer_login(store: CredentialStore) -> None:
    stale = login(store, "old-tok", refresh_token="rt-old")
    login(store, "fresh-tok", refresh_token="rt-fresh")

    store.rotate(stale, stale.with_token("old-tok-2", expires_at=None, refresh_token="rt-old-2"))

    loaded = store.load(API)
    assert loaded is not None
    assert loaded.access_token == "fresh-tok"


def test_memory_store_starts_from_records() -> None:
    store = MemoryCredentialStore([StoredCredentials(access_token="tok", api_url=f"{API}/")])

    loaded = store.load(API)

    assert loaded is not None
    assert loaded.api_url == API


def test_file_is_written_owner_only(path: Path) -> None:
    login(FileCredentialStore(path), "tok")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_leaves_no_temporary_file_behind(path: Path) -> None:
    login(FileCredentialStore(path), "tok")

    assert [entry.name for entry in path.parent.iterdir() if entry.name.endswith(".tmp")] == []


def test_second_save_keeps_the_first_record(path: Path) -> None:
    store = FileCredentialStore(path)
    login(store, "a")
    login(store, "b", STAGING)

    data = json.loads(path.read_text())
    assert set(data["records"]) == {
        credentials.record_key(API, CredentialKind.USER),
        credentials.record_key(STAGING, CredentialKind.USER),
    }


def test_existing_file_permissions_are_tightened_before_write(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path.write_text("{}")
    path.chmod(0o644)
    original_dump: Callable[..., None] = json.dump
    mode_during_write: list[int] = []

    def capture_mode(*args: object, **kwargs: object) -> None:
        destination = args[1]
        mode_during_write.append(stat.S_IMODE(os.fstat(destination.fileno()).st_mode))  # type: ignore[attr-defined]
        original_dump(*args, **kwargs)

    monkeypatch.setattr(credentials.json, "dump", capture_mode)
    login(FileCredentialStore(path), "tok")

    assert mode_during_write == [0o600]


def test_missing_or_corrupt_file_reads_as_empty(path: Path) -> None:
    store = FileCredentialStore(path)
    assert store.load() is None
    path.write_text("{not json")
    assert store.load() is None


def test_each_change_rereads_the_file(path: Path) -> None:
    """Two processes writing different records must not lose each other's."""
    first, second = FileCredentialStore(path), FileCredentialStore(path)
    record = login(first, "prod-tok", refresh_token="rt-1")
    login(second, "staging-tok", STAGING)

    first.rotate(record, record.with_token("prod-tok-2", expires_at=None, refresh_token="rt-2"))

    assert {c.access_token for c in second.records()} == {"prod-tok-2", "staging-tok"}


def test_default_store_follows_the_credentials_path(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "credentials_path", lambda: path)

    login(credentials.default_store(), "tok")

    assert path.exists()


def test_a_skipped_rotation_leaves_an_unreadable_file_alone(path: Path) -> None:
    path.write_text("{not json")
    record = StoredCredentials(access_token="tok", api_url=API, refresh_token="rt")

    replaced = FileCredentialStore(path).rotate(
        record, record.with_token("tok-2", expires_at=None, refresh_token="rt-2")
    )

    assert replaced is False
    assert path.read_text() == "{not json"


def test_a_rotation_reports_that_it_replaced_the_record(store: CredentialStore) -> None:
    record = login(store, "tok", refresh_token="rt-1")

    assert store.rotate(record, record.with_token("tok-2", expires_at=None, refresh_token="rt-2"))


@pytest.mark.parametrize("content", ["{not json", json.dumps({"version": 1, "records": {}})])
def test_a_login_sets_an_unreadable_file_aside_rather_than_overwriting_it(
    path: Path, content: str
) -> None:
    path.write_text(content)

    login(FileCredentialStore(path), "tok")

    assert path.with_name("credentials.json.unreadable").read_text() == content
    loaded = FileCredentialStore(path).load()
    assert loaded is not None
    assert loaded.access_token == "tok"


def _newer_store(path: Path) -> str:
    newer = json.dumps(
        {
            "version": credentials.STORE_VERSION + 1,
            "records": {
                f"{API}|user": {"access_token": "theirs", "api_url": API, "kind": "user"},
            },
            "active": {API: "user"},
            "default_api_url": API,
            "added_later": {"anything": True},
        }
    )
    path.write_text(newer)
    return newer


def test_a_newer_store_survives_a_login_from_this_version(path: Path) -> None:
    newer = _newer_store(path)

    with pytest.raises(AuthConfigurationError, match="newer bookshelf"):
        login(FileCredentialStore(path), "mine")

    assert path.read_text() == newer
    assert not path.with_name("credentials.json.unreadable").exists()


def test_a_newer_store_is_read_for_the_keys_this_version_knows(path: Path) -> None:
    _newer_store(path)

    loaded = FileCredentialStore(path).load(API)

    assert loaded is not None
    assert loaded.access_token == "theirs"


def test_a_rotation_into_a_newer_store_warns_and_leaves_it_alone(path: Path) -> None:
    newer = _newer_store(path)
    store = FileCredentialStore(path)
    record = store.load(API)
    assert record is not None

    with pytest.warns(UserWarning, match="not saved"):
        replaced = store.rotate(record, record.with_token("fresh", expires_at=None))

    assert replaced is False
    assert path.read_text() == newer


def test_a_held_lock_times_out_instead_of_hanging(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(credentials, "LOCK_TIMEOUT", 0.1)
    store = FileCredentialStore(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with (
        FileLock(path.with_name(f"{path.name}.lock")),
        pytest.raises(BookshelfError, match="credentials.json.lock"),
    ):
        # A second lock object in one process behaves like another process holding the file.
        login(store, "t1")
