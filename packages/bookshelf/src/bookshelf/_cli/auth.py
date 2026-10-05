"""``bookshelf auth`` commands over WorkOS AuthKit logins."""

import os
from datetime import UTC, datetime
from typing import Any

import httpx
import typer

from bookshelf._cli._runtime import (
    EXIT_AUTH_REQUIRED,
    EXIT_NETWORK,
    EXIT_UNEXPECTED,
    EXIT_USAGE,
    CliError,
    base_url,
    command_errors,
    command_group,
    emit,
    emit_json,
    emit_payload,
    emit_payloads,
    field,
    iso,
    note,
    with_remedy,
)
from bookshelf._core import credentials, errors, oauth, session
from bookshelf._core.auth import TokenProvider, decode_jwt_expiry
from bookshelf._core.client import BookshelfClient
from bookshelf._core.credentials import StoredCredentials, default_store
from bookshelf._core.resolution import (
    NEWER_STORE_REMEDY,
    CredentialSource,
    ResolvedCredential,
    resolve_credential,
)

auth_app = command_group("Manage authentication for the Bookshelf API.")


@auth_app.command("login")
def auth_login(
    no_browser: bool = typer.Option(
        False, "--no-browser", help="For a box that cannot open a browser."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the credential summary as JSON."),
) -> None:
    """Log in through WorkOS."""
    base = base_url()
    with command_errors():
        if default_store().read_only():
            raise CliError(
                f"{credentials.credentials_path()} was written by a newer bookshelf, "
                f"so this version cannot store a login in it. {NEWER_STORE_REMEDY}",
                exit_code=EXIT_USAGE,
            )
        _login_user(base, no_browser=no_browser, json_output=json_output)


def _login_user(base: str, *, no_browser: bool, json_output: bool) -> None:
    try:
        oauth.require_workos_client_id(base)
    except oauth.OAuthError as exc:
        raise CliError(str(exc), exit_code=EXIT_USAGE) from exc

    def show_code(flow: oauth.DeviceFlowInfo) -> None:
        note(field("Your code:", flow.user_code))
        note(field("Visit", flow.verification_uri_complete))
        note("")
        note("Waiting for authorisation...")

    def show_url(url: str) -> None:
        note("Opening browser for authentication...")
        note("If the browser does not open, visit this URL (or use --no-browser):")
        note("")
        note(f"  {url}")
        note("")

    try:
        me, record = session.login_user(
            base, browser=not no_browser, on_auth_url=show_url, on_device_code=show_code
        )
    except oauth.OAuthError as exc:
        raise CliError(f"authentication failed: {exc}", exit_code=EXIT_UNEXPECTED) from exc

    note(f"Logged in as {me.email}")
    note(field("Organisation", me.organization_id or "none"))
    note(field("Permissions", ", ".join(me.permissions or []) or "none"))
    note(field("Expires", iso(record.expires_at) or "never"))
    note(field("Stored", str(credentials.credentials_path())))
    if json_output:
        emit_json(
            {
                "kind": "user",
                "id": me.id,
                "subject": me.email,
                "organization_id": me.organization_id,
                "permissions": me.permissions or [],
                "expires_at": iso(record.expires_at),
                "api_url": base,
            }
        )


@auth_app.command("token")
def auth_token(
    json_output: bool = typer.Option(
        False, "--json", help="Emit the token and its deployment as JSON."
    ),
) -> None:
    """Print the current access token to stdout and nothing else."""
    base = base_url()
    with command_errors():
        credential = resolve_credential(base)
        remedy = credential.describe().remedy
        try:
            provider = credential.token_provider()
            if provider is None:
                raise CliError(
                    f"no stored credential for {base}. {remedy}", exit_code=EXIT_AUTH_REQUIRED
                )
            token = _current_token(provider, remedy=remedy)
            if json_output:
                emit_json({"access_token": token, "api_url": base})
            else:
                emit(token)
        except errors.AuthConfigurationError as exc:
            # A stored login that cannot be refreshed is spent as far as this command goes,
            # so it exits as a credential problem rather than a usage one.
            if credential.stored is not None:
                raise CliError(with_remedy(str(exc), remedy), exit_code=EXIT_AUTH_REQUIRED) from exc
            raise CliError(str(exc), exit_code=EXIT_USAGE) from exc


def _current_token(provider: TokenProvider, *, remedy: str) -> str:
    """Ask a provider for a token that is current, exchanging for a new one when one is due.

    The provider owns the staleness check, the single-flight lock
    and writing a rotated credential back over the record it came from,
    so printing a token and sending a request cannot disagree about any of them.
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            return provider.access_token(client.send)
    except httpx.TransportError as exc:
        raise CliError(f"token endpoint unreachable: {exc}", exit_code=EXIT_NETWORK) from exc
    except errors.AuthenticationError as exc:
        raise CliError(
            with_remedy(
                f"the credential could not be exchanged for a fresh token: {exc.detail}", remedy
            ),
            exit_code=EXIT_AUTH_REQUIRED,
        ) from exc


@auth_app.command("whoami")
def auth_whoami(
    offline: bool = typer.Option(
        False, "--offline", help="Report the stored credential without calling the API."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the report as JSON."),
) -> None:
    """Report the identity in play and which resolution step supplied it."""
    base = base_url()
    with command_errors():
        credential = resolve_credential(base)
        shadowed = credential.shadowed_login()
        shadows = (
            {"source": "stored_login", "id": shadowed.subject or shadowed.key}
            if shadowed is not None
            else None
        )
        report: dict[str, Any] = {
            "source": credential.source.value,
            "kind": "anonymous",
            "id": None,
            "organization_id": None,
            "permissions": [],
            "expires_at": None,
            "api_url": base,
            "shadows": shadows,
        }
        if credential.source is CredentialSource.NONE:
            report["reaches"] = "public"
        elif offline:
            _fill_offline(report, credential)
        else:
            _fill_online(report, base, credential)

        emit_payload(report, json_output=json_output)
        if shadows is not None and credential.source is CredentialSource.ENV_TOKEN:
            note("")
            note(f"Note: $BOOKSHELF_TOKEN overrides your stored login for {shadows['id']}.")
            note("      Unset it to use that instead.")


def _fill_offline(report: dict[str, Any], credential: ResolvedCredential) -> None:
    described = credential.describe()
    report["kind"] = described.kind
    report["id"] = described.subject
    report["organization_id"] = described.organization_id
    report["permissions"] = None
    report["expires_at"] = iso(described.expires_at)


def _fill_online(report: dict[str, Any], base: str, credential: ResolvedCredential) -> None:
    try:
        with BookshelfClient(base, auth=credential.auth(strict=True)) as client:
            me = client.get_current_user()
    except errors.AuthenticationError as exc:
        described = credential.describe()
        inspect = (
            " Run 'bookshelf auth whoami --offline' to inspect the stored record."
            if credential.source is CredentialSource.STORED_LOGIN
            else ""
        )
        raise CliError(
            f"the server rejected {described.label}: {_rejection_reason(credential)}. "
            f"{described.remedy}{inspect}",
            exit_code=EXIT_AUTH_REQUIRED,
        ) from exc
    described = credential.describe()
    report["kind"] = described.kind
    report["id"] = me.email or me.id
    report["organization_id"] = me.organization_id
    report["permissions"] = me.permissions or []
    report["expires_at"] = iso(described.expires_at)


def _rejection_reason(credential: ResolvedCredential) -> str:
    """Say why a credential was likely refused, from what can be read off it locally."""
    expires_at = credential.describe().expires_at
    if expires_at is not None and expires_at <= datetime.now(UTC):
        return f"it expired at {iso(expires_at)}"
    token = os.environ.get("BOOKSHELF_TOKEN", "")
    from_env = credential.source is CredentialSource.ENV_TOKEN
    if from_env and decode_jwt_expiry(token) is None:
        return "it is malformed, as it is not a JWT"
    return "it is revoked, or issued for another deployment"


@auth_app.command("logout")
def auth_logout(
    all_deployments: bool = typer.Option(
        False, "--all", help="Clear every stored login for every deployment."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the outcome as JSON."),
) -> None:
    """Clear stored credentials."""
    with command_errors():
        base = None if all_deployments else base_url()
        store = default_store()
        cleared = sorted(
            {record.api_url for record in store.records() if base is None or record.api_url == base}
        )
        # Unconditional, so records this version cannot read are purged as well.
        store.clear(base)
        if not cleared:
            note("Not logged in." if base is None else f"Not logged in to {base}.")
        for deployment in cleared:
            note(f"Cleared credentials for {deployment}")
        if json_output:
            emit_json({"cleared": cleared})


@auth_app.command("list")
def auth_list(
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object per login."),
) -> None:
    """List every stored login."""
    with command_errors():
        store = default_store()
        records = store.records()
        # This version never refreshes a token from a newer store, so expiry is the end of it.
        refreshable = not store.read_only()
        now = datetime.now(UTC)
        if not records:
            note(
                "No stored logins. Run 'bookshelf auth login' to add one."
                if refreshable
                else f"No stored logins this version can read. {NEWER_STORE_REMEDY}"
            )
            return
        emit_payloads(
            (_list_entry(record, now=now, refreshable=refreshable) for record in records),
            json_output=json_output,
        )


def _list_entry(record: StoredCredentials, *, now: datetime, refreshable: bool) -> dict[str, Any]:
    expired = record.expires_at is not None and record.expires_at <= now
    return {
        "id": record.subject,
        "api_url": record.api_url,
        "expired": expired,
        # Nothing this version can use renews it, so only a fresh login brings it back.
        "needs_login": expired and (not refreshable or record.refresh_token is None),
        "expires_at": iso(record.expires_at),
    }


__all__ = ["auth_app"]
