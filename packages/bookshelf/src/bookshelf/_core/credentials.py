"""Stored credentials for ``bookshelf auth login``, shared with the CLI.

The store holds several records at once, keyed by deployment plus identity kind
(``user`` for a WorkOS login, ``agent`` for a Bookshelf agent identity).
One record per deployment is active, and one deployment is the default.

Secrets have two possible homes:

1. **OS keychain** (primary, hardened store) under service name ``"bookshelf"``
   with one username per record secret (``"<key>:access_token"`` and friends).
   On read the keychain value takes precedence over the file copy.
2. **0600 JSON file** (secondary, compatibility store) at the ``platformdirs``
   user-config path ``bookshelf/credentials.json``.
   The file always holds the record index, because that is what names the keychain entries.
   It holds a secret only when the keychain could not take it.

When no keychain backend is available every keychain call degrades silently
to the file-only path.
Loading never refreshes, the credential providers own refresh.
"""

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from bookshelf._core.auth import decode_jwt_expiry

_KEYCHAIN_SERVICE = "bookshelf"

STORE_VERSION = 2

_SECRET_FIELDS = ("access_token", "refresh_token", "identity_assertion")


@dataclass(frozen=True)
class StoredCredentials:
    """One credential record persisted by ``bookshelf auth login``."""

    access_token: str
    token_type: str
    expires_at: datetime | None
    api_url: str
    refresh_token: str | None
    kind: str = "user"
    identity_assertion: str | None = None
    assertion_expires_at: datetime | None = None
    subject: str | None = None
    organization_id: str | None = None
    claimed: bool | None = None

    @property
    def key(self) -> str:
        return record_key(self.api_url, self.kind)


def normalise_api_url(api_url: str) -> str:
    """Canonicalise a deployment URL so equivalent spellings share one record."""
    return api_url.rstrip("/")


def record_key(api_url: str, kind: str) -> str:
    """Return the store key for one deployment plus identity kind."""
    return f"{normalise_api_url(api_url)}|{kind}"


def credentials_path() -> Path:
    """Return the path of the credentials file."""
    return Path(user_config_dir("bookshelf")) / "credentials.json"


def _keychain_call(operation: str, *args: str) -> str | None:
    """Invoke a keyring operation, swallowing every backend failure.

    A missing or broken keychain backend must never break login, load, or logout,
    so the caller falls back to the file copy.
    """
    try:
        import keyring

        result = getattr(keyring, operation)(_KEYCHAIN_SERVICE, *args)
        return None if result is None else str(result)
    except Exception:
        return None


def _keychain_set(username: str, value: str) -> bool:
    """Store one secret and confirm it can be read back.

    The return value decides whether the file copy is needed,
    so a backend that accepts a write it cannot serve must count as a failure.
    """
    _keychain_call("set_password", username, value)
    return _keychain_get(username) == value


def _keychain_get(username: str) -> str | None:
    return _keychain_call("get_password", username)


def _keychain_delete(username: str) -> None:
    _keychain_call("delete_password", username)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _read_store() -> dict[str, Any]:
    """Read the store file, treating an unknown version as empty."""
    creds_path = credentials_path()
    if not creds_path.exists():
        return {"version": STORE_VERSION, "records": {}, "active": {}}
    try:
        with creds_path.open("r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"version": STORE_VERSION, "records": {}, "active": {}}
    if not isinstance(data, dict):
        return {"version": STORE_VERSION, "records": {}, "active": {}}
    if data.get("version") != STORE_VERSION:
        # TODO: hook in future migrations here
        return {"version": STORE_VERSION, "records": {}, "active": {}}
    data.setdefault("records", {})
    data.setdefault("active", {})
    return data


def _write_store(store: dict[str, Any]) -> None:
    """Replace the store file atomically, so a partial write cannot destroy it.

    The temporary file is a sibling of the real one,
    because ``os.replace`` is only atomic within a single filesystem.
    """
    creds_path = credentials_path()
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = creds_path.with_name(f"{creds_path.name}.{os.getpid()}.tmp")
    try:
        # Created 0600 up front.
        # A chmod after the write would leave a window
        # where the secrets are world readable.
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            os.close(fd)
            raise
        with os.fdopen(fd, "w") as f:
            json.dump(store, f, indent=2)
        os.replace(temporary, creds_path)
    finally:
        temporary.unlink(missing_ok=True)


def _record_to_credentials(key: str, record: dict[str, Any]) -> StoredCredentials | None:
    access_token = _keychain_get(f"{key}:access_token") or record.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return None
    if not isinstance(record.get("api_url"), str):
        return None
    return StoredCredentials(
        access_token=access_token,
        token_type=str(record.get("token_type", "bearer")),
        expires_at=_parse_datetime(record.get("expires_at")),
        api_url=record["api_url"],
        refresh_token=_keychain_get(f"{key}:refresh_token") or record.get("refresh_token"),
        kind=str(record.get("kind", "user")),
        identity_assertion=(
            _keychain_get(f"{key}:identity_assertion") or record.get("identity_assertion")
        ),
        assertion_expires_at=_parse_datetime(record.get("assertion_expires_at")),
        subject=record.get("subject"),
        organization_id=record.get("organization_id"),
        claimed=record.get("claimed"),
    )


def load_credentials(api_url: str | None = None) -> StoredCredentials | None:
    """Load the active credential record, or ``None`` when missing or corrupt.

    With ``api_url``, the active record for that deployment.
    Without one,
    the active record is from the default deployment.
    This is the last deployment logged in to or switched to.
    Expired credentials are returned as stored,
    the credential provider decides whether they can still be refreshed.
    """
    store = _read_store()
    target = normalise_api_url(api_url) if api_url is not None else store.get("default_api_url")
    if not isinstance(target, str):
        return None
    kind = store.get("active", {}).get(target)
    if not isinstance(kind, str):
        return None
    key = record_key(target, kind)
    record = store.get("records", {}).get(key)
    if not isinstance(record, dict):
        return None
    return _record_to_credentials(key, record)


def list_credentials() -> list[StoredCredentials]:
    """Return every stored credential record."""
    store = _read_store()
    found: list[StoredCredentials] = []
    for key, record in store.get("records", {}).items():
        if isinstance(record, dict):
            credentials = _record_to_credentials(key, record)
            if credentials is not None:
                found.append(credentials)
    return found


def active_kinds() -> dict[str, str]:
    """Return the active identity kind per deployment."""
    store = _read_store()
    return {k: v for k, v in store.get("active", {}).items() if isinstance(v, str)}


def default_api_url() -> str | None:
    """Return the default deployment, or ``None`` when nothing is stored."""
    store = _read_store()
    value = store.get("default_api_url")
    return value if isinstance(value, str) else None


def save_credentials(
    access_token: str,
    *,
    api_url: str,
    kind: str = "user",
    refresh_token: str | None = None,
    expires_at: datetime | None = None,
    identity_assertion: str | None = None,
    assertion_expires_at: datetime | None = None,
    subject: str | None = None,
    organization_id: str | None = None,
    claimed: bool | None = None,
    token_type: str = "bearer",  # noqa: S107, this is the token type, not a secret
) -> None:
    """Persist one credential record and make it active for its deployment.

    When ``expires_at`` is ``None`` the expiry is derived from the access token's
    JWT ``exp`` claim, staying ``None`` only when the token carries no ``exp``.
    """
    if expires_at is None:
        exp = decode_jwt_expiry(access_token)
        if exp is not None:
            expires_at = datetime.fromtimestamp(exp, tz=UTC)

    api_url = normalise_api_url(api_url)
    key = record_key(api_url, kind)

    secrets: dict[str, str | None] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "identity_assertion": identity_assertion,
    }
    # A secret reaches the file only when the keychain could not take it.
    # The record itself always stays in the file,
    # because it is the index that names the keychain entries.
    for field in _SECRET_FIELDS:
        value = secrets[field]
        if value is None:
            _keychain_delete(f"{key}:{field}")
        elif _keychain_set(f"{key}:{field}", value):
            secrets[field] = None

    store = _read_store()
    store["records"][key] = {
        "access_token": secrets["access_token"],
        "token_type": token_type,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "api_url": api_url,
        "refresh_token": secrets["refresh_token"],
        "kind": kind,
        "identity_assertion": secrets["identity_assertion"],
        "assertion_expires_at": assertion_expires_at.isoformat() if assertion_expires_at else None,
        "subject": subject,
        "organization_id": organization_id,
        "claimed": claimed,
    }
    store["active"][api_url] = kind
    store["default_api_url"] = api_url
    _write_store(store)


def set_active(api_url: str, kind: str) -> StoredCredentials:
    """Make a stored identity active for its deployment without re-authenticating.

    The deployment also becomes the default,
    so the switched-to identity is what ambient resolution picks up.
    Raises ``KeyError`` when no such record is stored.
    """
    api_url = normalise_api_url(api_url)
    key = record_key(api_url, kind)
    store = _read_store()
    record = store.get("records", {}).get(key)
    if not isinstance(record, dict):
        raise KeyError(key)
    credentials = _record_to_credentials(key, record)
    if credentials is None:
        raise KeyError(key)
    store["active"][api_url] = kind
    store["default_api_url"] = api_url
    _write_store(store)
    return credentials


def _delete_record_secrets(key: str) -> None:
    for secret in _SECRET_FIELDS:
        _keychain_delete(f"{key}:{secret}")


def clear_credentials(api_url: str | None = None, kind: str | None = None) -> None:
    """Delete stored credentials from both the keychain and the file.

    Without arguments every record for every deployment is removed.
    With ``api_url`` only that deployment's records are removed,
    narrowed further to one identity kind when ``kind`` is given.
    """
    # Fixed keychain names written by the old single-slot store.
    # Delete them,
    # so stale secrets do not linger after a full logout.
    if api_url is None:
        _keychain_delete("access_token")
        _keychain_delete("refresh_token")

    store = _read_store()
    if api_url is None:
        for key in store.get("records", {}):
            _delete_record_secrets(key)
        creds_path = credentials_path()
        if creds_path.exists():
            creds_path.unlink()
        return

    api_url = normalise_api_url(api_url)
    kinds = [kind] if kind is not None else ["user", "agent"]
    for target_kind in kinds:
        key = record_key(api_url, target_kind)
        if store["records"].pop(key, None) is not None:
            _delete_record_secrets(key)
    active_kind = store.get("active", {}).get(api_url)
    if kind is None or active_kind == kind:
        store["active"].pop(api_url, None)
    if store.get("default_api_url") == api_url and api_url not in store["active"]:
        store["default_api_url"] = next(iter(store["active"]), None)
    _write_store(store)


__all__ = [
    "STORE_VERSION",
    "StoredCredentials",
    "active_kinds",
    "clear_credentials",
    "credentials_path",
    "default_api_url",
    "list_credentials",
    "load_credentials",
    "normalise_api_url",
    "record_key",
    "save_credentials",
    "set_active",
]
