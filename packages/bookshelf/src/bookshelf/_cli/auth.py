"""``bookshelf auth`` commands over two identity systems.

WorkOS AuthKit issues credentials for humans,
Bookshelf's own authorization server issues ``bsat_`` tokens for agents,
and ``--agent`` selects which.
"""

import os
import time
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
    emit,
    emit_json,
    emit_payload,
    emit_payloads,
    field,
    iso,
    note,
    requested_api_url,
)
from bookshelf._core import config, credentials, errors, oauth, session
from bookshelf._core.auth import (
    JWT_BEARER_GRANT,
    ActionsOidcToken,
    TokenProvider,
    decode_jwt_expiry,
)
from bookshelf._core.client import BookshelfClient
from bookshelf._core.config import CredentialSource
from bookshelf._core.credentials import CredentialKind
from bookshelf._generated import models

CLAIM_GRANT = "urn:workos:agent-auth:grant-type:claim"

_AGENT_PLATFORM = "bookshelf-cli"

_LOGIN_REMEDY = (
    "Run 'bookshelf auth login' to sign in, "
    "or 'bookshelf auth login --agent' to register an agent identity."
)

auth_app = typer.Typer(help="Manage authentication for the Bookshelf API.", no_args_is_help=True)


@auth_app.command("login")
def auth_login(
    agent: bool = typer.Option(
        False, "--agent", help="Register an agent identity instead of a human login."
    ),
    claim: bool = typer.Option(
        False, "--claim", help="Run the claim ceremony so a human binds the identity."
    ),
    email: str | None = typer.Option(
        None, "--email", help="Email the approving human signs in with. Required with --claim."
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="For a box that cannot open a browser."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the credential summary as JSON."),
) -> None:
    """Log in: through WorkOS as a human, or as an agent with --agent."""
    base = base_url()
    with command_errors():
        if not agent:
            if claim or email is not None:
                raise CliError(
                    "--claim and --email require --agent. "
                    "Run 'bookshelf auth login --agent --claim --email you@org.com'.",
                    exit_code=EXIT_USAGE,
                )
            _login_user(base, no_browser=no_browser, json_output=json_output)
        elif claim:
            if email is None:
                raise CliError(
                    "--claim requires --email so approval can be bound to your user. "
                    "Run 'bookshelf auth login --agent --claim --email you@org.com'.",
                    exit_code=EXIT_USAGE,
                )
            _login_agent_claim(base, email=email, json_output=json_output)
        else:
            _login_agent_anonymous(base, json_output=json_output)


def _login_user(base: str, *, no_browser: bool, json_output: bool) -> None:
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


def _login_agent_anonymous(base: str, *, json_output: bool) -> None:
    with BookshelfClient(base, auth=None) as client:
        registration = client.register_agent_identity(
            models.AgentIdentityRequest(type=models.Type.anonymous, agent_platform=_AGENT_PLATFORM)
        )
        assert isinstance(registration, models.AnonymousRegistrationResponse)
        grant = client.agent_token_exchange(
            models.BodyAgentTokenExchange(
                grant_type=JWT_BEARER_GRANT,
                assertion=registration.identity_assertion,
            )
        )
    assertion = grant.identity_assertion or registration.identity_assertion
    assertion_expires = grant.assertion_expires or registration.assertion_expires
    expires_at = credentials.expiry_from(grant.expires_in)
    subject = f"agent:{registration.registration_id}"
    scopes = grant.scope.split()
    credentials.save_credentials(
        grant.access_token,
        api_url=base,
        kind=CredentialKind.AGENT,
        expires_at=expires_at,
        identity_assertion=assertion,
        assertion_expires_at=assertion_expires,
        subject=subject,
        claimed=False,
    )
    note(f"Registered agent identity {subject}")
    note(field("Permissions", ", ".join(scopes) or "none"))
    note(field("Reaches", "public books only"))
    note(field("Expires", f"{iso(expires_at)} (assertion {iso(assertion_expires)})"))
    note("")
    note(
        "Run 'bookshelf auth login --agent --claim --email you@org.com' "
        "for organisation access and writes."
    )
    if json_output:
        emit_json(
            {
                "kind": "agent",
                "claimed": False,
                "id": subject,
                "permissions": scopes,
                "reaches": "public",
                "expires_at": iso(expires_at),
                "identity_assertion": assertion,
                "assertion_expires_at": iso(assertion_expires),
                "api_url": base,
            }
        )


def _login_agent_claim(base: str, *, email: str, json_output: bool) -> None:
    with BookshelfClient(base, auth=None) as client:
        registration = client.register_agent_identity(
            models.AgentIdentityRequest(
                type=models.Type.service_auth,
                login_hint=email,
                agent_platform=_AGENT_PLATFORM,
            )
        )
        assert isinstance(registration, models.ServiceAuthRegistrationResponse)
        ceremony = registration.claim
        note("Ask your user to approve this agent:")
        note("")
        note(f"  Visit       {ceremony.verification_uri}")
        note(f"  Enter code  {ceremony.user_code}")
        note("")
        note(f"Waiting for approval (expires in {max(ceremony.expires_in // 60, 1)} minutes)...")
        grant = _poll_claim(
            client,
            claim_token=registration.claim_token,
            interval=ceremony.interval,
            expires_in=ceremony.expires_in,
        )
        me = _identity_for_token(base, grant.access_token)
    expires_at = credentials.expiry_from(grant.expires_in)
    subject = me.email or email
    credentials.save_credentials(
        grant.access_token,
        api_url=base,
        kind=CredentialKind.AGENT,
        expires_at=expires_at,
        identity_assertion=grant.identity_assertion,
        assertion_expires_at=grant.assertion_expires,
        subject=subject,
        organization_id=me.organization_id,
        claimed=True,
    )
    scopes = grant.scope.split()
    note(f"Claimed by {subject}")
    note(field("Organisation", me.organization_id or "none"))
    note(field("Permissions", ", ".join(scopes) or "none"))
    if json_output:
        emit_json(
            {
                "kind": "agent",
                "claimed": True,
                "id": me.id,
                "subject": subject,
                "organization_id": me.organization_id,
                "permissions": scopes,
                "expires_at": iso(expires_at),
                "identity_assertion": grant.identity_assertion,
                "assertion_expires_at": iso(grant.assertion_expires),
                "api_url": base,
            }
        )


def _poll_claim(
    client: BookshelfClient, *, claim_token: str, interval: int, expires_in: int
) -> models.TokenResponse:
    deadline = time.monotonic() + expires_in
    wait = max(interval, 1)
    while True:
        try:
            return client.agent_token_exchange(
                models.BodyAgentTokenExchange(grant_type=CLAIM_GRANT, claim_token=claim_token)
            )
        except errors.OAuthProtocolError as exc:
            if exc.error == "authorization_pending":
                pass
            elif exc.error == "slow_down":
                wait += 5
            else:
                raise CliError(
                    f"claim was not completed: {exc.detail} "
                    "Run 'bookshelf auth login --agent --claim --email you@org.com' to retry.",
                    exit_code=EXIT_AUTH_REQUIRED,
                ) from exc
        if time.monotonic() >= deadline:
            raise CliError(
                "claim ceremony expired before approval. "
                "Run 'bookshelf auth login --agent --claim --email you@org.com' to retry.",
                exit_code=EXIT_AUTH_REQUIRED,
            )
        time.sleep(wait)


def _identity_for_token(base: str, access_token: str) -> models.UserResponse:
    with BookshelfClient(base, auth=access_token) as client:
        return client.get_current_user()


@auth_app.command("token")
def auth_token() -> None:
    """Print the current access token to stdout and nothing else."""
    base = base_url()
    with command_errors():
        source, stored = config.resolve_ambient_credential(base)
        if source is CredentialSource.ENV_TOKEN:
            emit(os.environ["BOOKSHELF_TOKEN"])
            return
        if source is CredentialSource.ACTIONS_OIDC:
            try:
                emit(
                    _current_token(
                        ActionsOidcToken(),
                        remedy="Give the job the 'id-token: write' permission.",
                    )
                )
            except errors.AuthConfigurationError as exc:
                raise CliError(str(exc), exit_code=EXIT_USAGE) from exc
            return
        if source is CredentialSource.CLIENT_CREDENTIALS:
            try:
                machine = config.client_credentials_from_environment()
            except errors.AuthConfigurationError as exc:
                raise CliError(str(exc), exit_code=EXIT_USAGE) from exc
            emit(
                _current_token(
                    machine,
                    remedy="Check BOOKSHELF_CLIENT_ID, BOOKSHELF_CLIENT_SECRET "
                    "and BOOKSHELF_TOKEN_URL against the issuer.",
                )
            )
            return
        if stored is None:
            raise CliError(
                f"no stored credential for {base}. {_LOGIN_REMEDY}",
                exit_code=EXIT_AUTH_REQUIRED,
            )
        try:
            provider = config.auth_from_stored(stored)
        except errors.AuthConfigurationError as exc:
            # A stored login that cannot be refreshed is spent as far as this command goes,
            # so it exits as a credential problem rather than an unexpected one.
            raise CliError(f"{exc} {_LOGIN_REMEDY}", exit_code=EXIT_AUTH_REQUIRED) from exc
        emit(_current_token(provider, remedy=_LOGIN_REMEDY))


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
            f"the credential could not be exchanged for a fresh token: {exc.detail} {remedy}",
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
        source, stored = config.resolve_ambient_credential(base)
        if source in (
            CredentialSource.ENV_TOKEN,
            CredentialSource.ACTIONS_OIDC,
            CredentialSource.CLIENT_CREDENTIALS,
        ):
            stored = credentials.load_credentials(base)
        shadows: dict[str, str] | None = None
        if source is not CredentialSource.STORED_LOGIN and stored is not None:
            shadows = {
                "source": "stored_login",
                "id": stored.subject or credentials.record_key(stored.api_url, stored.kind),
            }

        report: dict[str, Any] = {
            "source": source.value,
            "kind": "anonymous",
            "id": None,
            "organization_id": None,
            "permissions": [],
            "expires_at": None,
            "api_url": base,
            "shadows": shadows,
        }
        if source is CredentialSource.NONE:
            report["reaches"] = "public"
        elif offline:
            _fill_offline(report, source, stored)
        else:
            _fill_online(report, base, source, stored)

        emit_payload(report, json_output=json_output)
        if shadows is not None and source is CredentialSource.ENV_TOKEN:
            note("")
            note(f"Note: $BOOKSHELF_TOKEN overrides your stored login for {shadows['id']}.")
            note("      Unset it to use that instead.")


def _fill_offline(
    report: dict[str, Any],
    source: CredentialSource,
    stored: credentials.StoredCredentials | None,
) -> None:
    if source is CredentialSource.ENV_TOKEN:
        token = os.environ["BOOKSHELF_TOKEN"]
        report["kind"] = "agent" if token.startswith("bsat_") else "user"
        exp = decode_jwt_expiry(token)
        if exp is not None:
            report["expires_at"] = iso(datetime.fromtimestamp(exp, tz=UTC))
        return
    if source is CredentialSource.ACTIONS_OIDC:
        report["kind"] = "machine"
        return
    if source is CredentialSource.CLIENT_CREDENTIALS:
        report["kind"] = "user"
        return
    assert stored is not None
    report["kind"] = str(stored.kind)
    report["id"] = stored.subject
    report["organization_id"] = stored.organization_id
    report["expires_at"] = iso(stored.expires_at)
    if stored.kind is CredentialKind.AGENT:
        report["claimed"] = bool(stored.claimed)
        if not stored.claimed:
            report["reaches"] = "public"


def _fill_online(
    report: dict[str, Any],
    base: str,
    source: CredentialSource,
    stored: credentials.StoredCredentials | None,
) -> None:
    auth = (
        config.auth_from_stored(stored)
        if source is CredentialSource.STORED_LOGIN and stored is not None
        else config.UNSET
    )
    try:
        with BookshelfClient(base, auth=auth) as client:
            me = client.get_current_user()
    except errors.AuthenticationError as exc:
        raise CliError(
            "the credential in play is revoked or expired (the server rejected it). "
            "Run 'bookshelf auth login' to sign in again, "
            "or 'bookshelf auth whoami --offline' to inspect the stored record.",
            exit_code=EXIT_AUTH_REQUIRED,
        ) from exc
    is_agent = me.id.startswith("agent:")
    report["kind"] = "agent" if is_agent else "user"
    report["id"] = me.id if is_agent else (me.email or me.id)
    report["organization_id"] = me.organization_id
    report["permissions"] = me.permissions or []
    if is_agent:
        claimed = me.organization_id is not None
        report["claimed"] = claimed
        if not claimed:
            report["reaches"] = "public"
    if source is CredentialSource.STORED_LOGIN and stored is not None:
        report["expires_at"] = iso(stored.expires_at)


@auth_app.command("logout")
def auth_logout(
    all_deployments: bool = typer.Option(
        False, "--all", help="Clear every stored identity for every deployment."
    ),
    no_revoke: bool = typer.Option(
        False, "--no-revoke", help="Skip server-side revocation and only clear local state."
    ),
) -> None:
    """Revoke and clear stored credentials. Local state is cleared even when revocation fails."""
    with command_errors():
        base = None if all_deployments else base_url()
        records = [
            record
            for record in credentials.list_credentials()
            if base is None or record.api_url == base
        ]
        cleared = {record.api_url for record in records}
        if not cleared:
            note("Not logged in." if base is None else f"Not logged in to {base}.")
            return

        failed: list[str] = []
        for record in records:
            if record.kind is not CredentialKind.AGENT or no_revoke:
                continue
            try:
                with BookshelfClient(record.api_url, auth=None) as client:
                    client.agent_token_revoke(
                        models.BodyAgentTokenRevoke(token=record.access_token)
                    )
                note(f"Revoked agent token for {record.subject or record.api_url}")
            except errors.BookshelfError:
                failed.append(record.api_url)

        credentials.clear_credentials(base)
        for deployment in sorted(cleared):
            note(f"Cleared credentials for {deployment}")

        if failed:
            raise CliError(
                "revocation failed for: " + ", ".join(sorted(set(failed))) + ". "
                "The token may still be live. Run 'bookshelf auth logout' again to retry.",
                exit_code=EXIT_NETWORK,
            )


@auth_app.command("list")
def auth_list(
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object per identity."),
) -> None:
    """List every stored identity, marking the active one per deployment."""
    with command_errors():
        records = credentials.list_credentials()
        active = credentials.active_kinds()
        if not records:
            note("No stored identities. Run 'bookshelf auth login' to add one.")
            return
        emit_payloads(
            (
                {
                    "kind": str(record.kind),
                    "id": record.subject,
                    "api_url": record.api_url,
                    "active": active.get(record.api_url) == record.kind,
                    "claimed": record.claimed,
                    "expires_at": iso(record.expires_at),
                    "assertion_expires_at": iso(record.assertion_expires_at),
                }
                for record in records
            ),
            json_output=json_output,
        )


@auth_app.command("switch")
def auth_switch(
    identity: str = typer.Argument(help="The identity to make active, as shown by 'auth list'."),
) -> None:
    """Make a stored identity active without re-authenticating."""
    with command_errors():
        records = [
            record for record in credentials.list_credentials() if record.subject == identity
        ]
        if requested_api_url() is not None:
            base = base_url()
            records = [record for record in records if record.api_url == base]
        if not records:
            raise CliError(
                f"no stored identity {identity!r}. "
                "Run 'bookshelf auth list' to see what this machine holds.",
                exit_code=EXIT_USAGE,
            )
        if len(records) > 1:
            raise CliError(
                f"identity {identity!r} exists on several deployments. Pass --api-url to pick one.",
                exit_code=EXIT_USAGE,
            )
        record = records[0]
        credentials.set_active(record.api_url, record.kind)
        note(f"Switched to {identity} ({record.api_url})")


__all__ = ["auth_app"]
