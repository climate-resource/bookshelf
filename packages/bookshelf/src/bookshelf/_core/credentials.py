"""Stored credentials for ``bookshelf auth login``, shared with the CLI.

The store holds several records at once, keyed by deployment plus identity kind
(``user`` for a WorkOS login, ``agent`` for a Bookshelf agent identity).
One record per deployment is active, and one deployment is the default.

:class:`FileCredentialStore` keeps them in a JSON file at the ``platformdirs`` user-config path
``bookshelf/credentials.json``, readable only by the current user.
:class:`MemoryCredentialStore` applies the same rules without touching disk.
"""

import copy
import enum
import json
import os
import stat
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from filelock import FileLock
from platformdirs import user_config_dir

from bookshelf._core.auth import decode_jwt_expiry

STORE_VERSION = 2


class CredentialKind(enum.StrEnum):
    """Which identity system issued a stored credential.

    The values are what the store file holds,
    so naming them here does not move the on-disk format.
    """

    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True, kw_only=True)
class StoredCredentials:
    """One credential record persisted by ``bookshelf auth login``."""

    access_token: str
    api_url: str
    token_type: str = "bearer"
    expires_at: datetime | None = None
    refresh_token: str | None = None
    kind: CredentialKind = CredentialKind.USER
    identity_assertion: str | None = None
    assertion_expires_at: datetime | None = None
    subject: str | None = None
    organization_id: str | None = None
    claimed: bool | None = None

    @property
    def key(self) -> str:
        """The store key this record lives under."""
        return record_key(self.api_url, self.kind)

    def with_token(
        self,
        access_token: str,
        *,
        expires_at: datetime | None,
        refresh_token: str | None = None,
        identity_assertion: str | None = None,
        assertion_expires_at: datetime | None = None,
    ) -> "StoredCredentials":
        """Return this record carrying a freshly minted access token.

        Everything the mint did not replace is carried over,
        so a rotation cannot drop the subject, the organisation
        or the claim that the record was bound to.
        A secret left out keeps the one already stored,
        because an issuer that does not rotate returns nothing in its place.
        """
        return replace(
            self,
            access_token=access_token,
            expires_at=expires_at,
            refresh_token=self.refresh_token if refresh_token is None else refresh_token,
            identity_assertion=(
                self.identity_assertion if identity_assertion is None else identity_assertion
            ),
            assertion_expires_at=(
                self.assertion_expires_at if assertion_expires_at is None else assertion_expires_at
            ),
        )


def normalise_api_url(api_url: str) -> str:
    """Canonicalise a deployment URL so equivalent spellings share one record."""
    return api_url.rstrip("/")


def record_key(api_url: str, kind: CredentialKind) -> str:
    """Return the store key for one deployment plus identity kind."""
    return f"{normalise_api_url(api_url)}|{kind}"


def credentials_path() -> Path:
    """Return the path of the credentials file."""
    return Path(user_config_dir("bookshelf")) / "credentials.json"


def expiry_from(expires_in: float | None) -> datetime | None:
    """Turn a token response's ``expires_in`` seconds into the moment it expires."""
    return None if expires_in is None else datetime.now(UTC) + timedelta(seconds=expires_in)


class CredentialStore(Protocol):
    """Where stored logins live, and the rules for which one is in play."""

    def load(self, api_url: str | None = None) -> StoredCredentials | None:
        """Return the active record for ``api_url``, or for the default deployment without one.

        Expired credentials are returned as stored,
        the credential provider decides whether they can still be refreshed.
        """
        ...

    def records(self) -> list[StoredCredentials]:
        """Return every stored record."""
        ...

    def active_kinds(self) -> dict[str, CredentialKind]:
        """Return the active identity kind per deployment."""
        ...

    def save_login(self, record: StoredCredentials) -> StoredCredentials:
        """Store a fresh login, make it active and its deployment the default, and return it.

        A record with no ``expires_at`` takes its expiry from the access token's JWT ``exp`` claim.
        """
        ...

    def rotate(self, previous: StoredCredentials, current: StoredCredentials) -> bool:
        """Replace ``previous`` with its refreshed form, leaving the default deployment alone.

        Nothing is written when the stored record is no longer ``previous``,
        so a refresh cannot bring back a logged out login or overwrite a newer one.
        Returns whether the record was replaced.
        """
        ...

    def set_active(self, api_url: str, kind: CredentialKind) -> StoredCredentials:
        """Make a stored identity active and its deployment the default.

        Raises ``KeyError`` when no such record is stored.
        """
        ...

    def clear(self, api_url: str | None = None, kind: CredentialKind | None = None) -> None:
        """Delete every record, one deployment's records, or one identity on one deployment."""
        ...


def _empty() -> dict[str, Any]:
    return {"version": STORE_VERSION, "records": {}, "active": {}}


def _parse_kind(value: Any) -> CredentialKind | None:
    try:
        return CredentialKind(value)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _record_to_credentials(record: dict[str, Any]) -> StoredCredentials | None:
    access_token = record.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return None
    if not isinstance(record.get("api_url"), str):
        return None
    # A kind this version does not know is a record it cannot serve.
    kind = _parse_kind(record.get("kind", CredentialKind.USER))
    if kind is None:
        return None
    return StoredCredentials(
        access_token=access_token,
        token_type=str(record.get("token_type", "bearer")),
        expires_at=_parse_datetime(record.get("expires_at")),
        api_url=record["api_url"],
        refresh_token=record.get("refresh_token"),
        kind=kind,
        identity_assertion=record.get("identity_assertion"),
        assertion_expires_at=_parse_datetime(record.get("assertion_expires_at")),
        subject=record.get("subject"),
        organization_id=record.get("organization_id"),
        claimed=record.get("claimed"),
    )


def _credentials_to_record(record: StoredCredentials) -> dict[str, Any]:
    return {
        "access_token": record.access_token,
        "token_type": record.token_type,
        "expires_at": _iso(record.expires_at),
        "api_url": record.api_url,
        "refresh_token": record.refresh_token,
        "kind": str(record.kind),
        "identity_assertion": record.identity_assertion,
        "assertion_expires_at": _iso(record.assertion_expires_at),
        "subject": record.subject,
        "organization_id": record.organization_id,
        "claimed": record.claimed,
    }


def _normalised(record: StoredCredentials) -> StoredCredentials:
    expires_at = record.expires_at
    if expires_at is None:
        exp = decode_jwt_expiry(record.access_token)
        if exp is not None:
            expires_at = datetime.fromtimestamp(exp, tz=UTC)
    return replace(record, expires_at=expires_at, api_url=normalise_api_url(record.api_url))


class _DocumentStore(ABC):
    """The store rules over one JSON-shaped document, whichever adapter holds it."""

    @abstractmethod
    def _read(self) -> dict[str, Any]:
        """Return a snapshot of the document."""

    @abstractmethod
    @contextmanager
    def _update(self) -> Iterator[dict[str, Any]]:
        """Yield the current document for changing in place, then persist it if it changed."""

    def load(self, api_url: str | None = None) -> StoredCredentials | None:
        store = self._read()
        target = normalise_api_url(api_url) if api_url is not None else store.get("default_api_url")
        if not isinstance(target, str):
            return None
        kind = _parse_kind(store["active"].get(target))
        if kind is None:
            return None
        record = store["records"].get(record_key(target, kind))
        return _record_to_credentials(record) if isinstance(record, dict) else None

    def records(self) -> list[StoredCredentials]:
        found = (
            _record_to_credentials(record)
            for record in self._read()["records"].values()
            if isinstance(record, dict)
        )
        return [credentials for credentials in found if credentials is not None]

    def active_kinds(self) -> dict[str, CredentialKind]:
        parsed = {key: _parse_kind(value) for key, value in self._read()["active"].items()}
        return {key: kind for key, kind in parsed.items() if kind is not None}

    def save_login(self, record: StoredCredentials) -> StoredCredentials:
        record = _normalised(record)
        with self._update() as store:
            store["records"][record.key] = _credentials_to_record(record)
            store["active"][record.api_url] = str(record.kind)
            store["default_api_url"] = record.api_url
        return record

    def rotate(self, previous: StoredCredentials, current: StoredCredentials) -> bool:
        previous, current = _normalised(previous), _normalised(current)
        with self._update() as store:
            stored = store["records"].get(previous.key)
            if not isinstance(stored, dict) or stored.get("access_token") != previous.access_token:
                return False
            del store["records"][previous.key]
            store["records"][current.key] = _credentials_to_record(current)
            # A rotation can change the kind a record is served as, and the identity stays active.
            if store["active"].get(previous.api_url) == str(previous.kind):
                store["active"][current.api_url] = str(current.kind)
        return True

    def set_active(self, api_url: str, kind: CredentialKind) -> StoredCredentials:
        api_url = normalise_api_url(api_url)
        key = record_key(api_url, kind)
        with self._update() as store:
            record = store["records"].get(key)
            credentials = _record_to_credentials(record) if isinstance(record, dict) else None
            if credentials is None:
                raise KeyError(key)
            store["active"][api_url] = str(kind)
            store["default_api_url"] = api_url
        return credentials

    def clear(self, api_url: str | None = None, kind: CredentialKind | None = None) -> None:
        with self._update() as store:
            if api_url is None:
                store.clear()
                store.update(_empty())
                return
            api_url = normalise_api_url(api_url)
            kinds = [kind] if kind is not None else list(CredentialKind)
            for target_kind in kinds:
                store["records"].pop(record_key(api_url, target_kind), None)
            active_kind = store["active"].get(api_url)
            if kind is None or active_kind == kind:
                store["active"].pop(api_url, None)
            if store.get("default_api_url") == api_url and api_url not in store["active"]:
                store["default_api_url"] = next(iter(store["active"]), None)


class FileCredentialStore(_DocumentStore):
    """The credentials file, locked across processes for every change.

    Every change re-reads the file under the lock,
    so two processes rotating different records cannot lose each other's writes.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        """The file this store reads and writes."""
        return self._path if self._path is not None else credentials_path()

    def _read(self) -> dict[str, Any]:
        try:
            with self.path.open("r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return _empty()
        if not isinstance(data, dict) or data.get("version") != STORE_VERSION:
            # TODO: hook in future migrations here
            return _empty()
        data.setdefault("records", {})
        data.setdefault("active", {})
        return data

    @contextmanager
    def _update(self) -> Iterator[dict[str, Any]]:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(path.with_name(f"{path.name}.lock")):
            store = self._read()
            before = copy.deepcopy(store)
            yield store
            if store != before:
                self._write(store)

    def _write(self, store: dict[str, Any]) -> None:
        path = self.path
        # Written beside the file and moved over it, so a crash never leaves it half written.
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
            )
            try:
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                os.close(fd)
                raise
            with os.fdopen(fd, "w") as f:
                json.dump(store, f, indent=2)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class MemoryCredentialStore(_DocumentStore):
    """A store held in memory, for tests and for processes that must not touch disk."""

    def __init__(self, records: Iterable[StoredCredentials] = ()) -> None:
        self._store = _empty()
        for record in records:
            self.save_login(record)

    def _read(self) -> dict[str, Any]:
        return copy.deepcopy(self._store)

    @contextmanager
    def _update(self) -> Iterator[dict[str, Any]]:
        store = self._read()
        yield store
        self._store = store


def default_store() -> CredentialStore:
    """Return the store ``bookshelf auth login`` writes to."""
    return FileCredentialStore()


__all__ = [
    "STORE_VERSION",
    "CredentialKind",
    "CredentialStore",
    "FileCredentialStore",
    "MemoryCredentialStore",
    "StoredCredentials",
    "credentials_path",
    "default_store",
    "expiry_from",
    "normalise_api_url",
    "record_key",
]
