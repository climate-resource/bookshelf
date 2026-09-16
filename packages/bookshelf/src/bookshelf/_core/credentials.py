"""Stored credentials for ``bookshelf auth login``, shared with the CLI.

The store holds several records at once, keyed by deployment plus identity kind
(``user`` for a WorkOS login, ``agent`` for a Bookshelf agent identity).
One record per deployment is active, and one deployment is the default.

Secrets live in a JSON file at the ``platformdirs`` user-config path
``bookshelf/credentials.json``, readable only by the current user.
"""

import enum
import json
import os
import stat
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class StoredCredentials:
    """One credential record persisted by ``bookshelf auth login``."""

    access_token: str
    token_type: str
    expires_at: datetime | None
    api_url: str
    refresh_token: str | None
    kind: CredentialKind = CredentialKind.USER
    identity_assertion: str | None = None
    assertion_expires_at: datetime | None = None
    subject: str | None = None
    organization_id: str | None = None
    claimed: bool | None = None

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
    creds_path = credentials_path()
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    # Make a temp file and then os.remove to avoid corrupted writes
    temporary = creds_path.with_name(f"{creds_path.name}.{os.getpid()}.tmp")
    try:
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
    kind = _parse_kind(store.get("active", {}).get(target))
    if kind is None:
        return None
    key = record_key(target, kind)
    record = store.get("records", {}).get(key)
    if not isinstance(record, dict):
        return None
    return _record_to_credentials(record)


def list_credentials() -> list[StoredCredentials]:
    """Return every stored credential record."""
    store = _read_store()
    found: list[StoredCredentials] = []
    for record in store.get("records", {}).values():
        if isinstance(record, dict):
            credentials = _record_to_credentials(record)
            if credentials is not None:
                found.append(credentials)
    return found


def active_kinds() -> dict[str, CredentialKind]:
    """Return the active identity kind per deployment."""
    store = _read_store()
    parsed = {key: _parse_kind(value) for key, value in store.get("active", {}).items()}
    return {key: kind for key, kind in parsed.items() if kind is not None}


def save_credentials(
    access_token: str,
    *,
    api_url: str,
    kind: CredentialKind = CredentialKind.USER,
    refresh_token: str | None = None,
    expires_at: datetime | None = None,
    identity_assertion: str | None = None,
    assertion_expires_at: datetime | None = None,
    subject: str | None = None,
    organization_id: str | None = None,
    claimed: bool | None = None,
    token_type: str = "bearer",  # noqa: S107, this is the token type, not a secret
) -> None:
    """Persist one freshly acquired credential and make it active for its deployment.

    This is the shape a login has, where there is no prior record to build on.
    """
    save_record(
        StoredCredentials(
            access_token=access_token,
            token_type=token_type,
            expires_at=expires_at,
            api_url=api_url,
            refresh_token=refresh_token,
            kind=kind,
            identity_assertion=identity_assertion,
            assertion_expires_at=assertion_expires_at,
            subject=subject,
            organization_id=organization_id,
            claimed=claimed,
        )
    )


def save_record(record: StoredCredentials) -> None:
    """Persist one credential record and make it active for its deployment.

    A record with no ``expires_at`` takes its expiry from the access token's JWT ``exp`` claim,
    staying open-ended only when the token carries no ``exp``.
    """
    expires_at = record.expires_at
    if expires_at is None:
        exp = decode_jwt_expiry(record.access_token)
        if exp is not None:
            expires_at = datetime.fromtimestamp(exp, tz=UTC)

    api_url = normalise_api_url(record.api_url)
    kind = record.kind
    key = record_key(api_url, kind)

    store = _read_store()
    assertion_expiry = record.assertion_expires_at
    store["records"][key] = {
        "access_token": record.access_token,
        "token_type": record.token_type,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "api_url": api_url,
        "refresh_token": record.refresh_token,
        "kind": str(kind),
        "identity_assertion": record.identity_assertion,
        "assertion_expires_at": assertion_expiry.isoformat() if assertion_expiry else None,
        "subject": record.subject,
        "organization_id": record.organization_id,
        "claimed": record.claimed,
    }
    store["active"][api_url] = str(kind)
    store["default_api_url"] = api_url
    _write_store(store)


def set_active(api_url: str, kind: CredentialKind) -> StoredCredentials:
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
    credentials = _record_to_credentials(record)
    if credentials is None:
        raise KeyError(key)
    store["active"][api_url] = str(kind)
    store["default_api_url"] = api_url
    _write_store(store)
    return credentials


def clear_credentials(api_url: str | None = None, kind: CredentialKind | None = None) -> None:
    """Delete stored credentials from the file.

    Without arguments every record for every deployment is removed.
    With ``api_url`` only that deployment's records are removed,
    narrowed further to one identity kind when ``kind`` is given.
    """
    if api_url is None:
        creds_path = credentials_path()
        if creds_path.exists():
            creds_path.unlink()
        return

    store = _read_store()
    api_url = normalise_api_url(api_url)
    kinds = [kind] if kind is not None else list(CredentialKind)
    for target_kind in kinds:
        store["records"].pop(record_key(api_url, target_kind), None)
    active_kind = store.get("active", {}).get(api_url)
    if kind is None or active_kind == kind:
        store["active"].pop(api_url, None)
    if store.get("default_api_url") == api_url and api_url not in store["active"]:
        store["default_api_url"] = next(iter(store["active"]), None)
    _write_store(store)


__all__ = [
    "STORE_VERSION",
    "CredentialKind",
    "StoredCredentials",
    "active_kinds",
    "clear_credentials",
    "credentials_path",
    "list_credentials",
    "load_credentials",
    "normalise_api_url",
    "record_key",
    "save_credentials",
    "save_record",
    "set_active",
]
