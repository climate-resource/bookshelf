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
    command_group,
    emit,
    emit_json,
    emit_payload,
    emit_payloads,
    field,
    iso,
    note,
    requested_api_url,
    with_remedy,
)
from bookshelf._core import credentials, errors, oauth, session
from bookshelf._core.auth import JWT_BEARER_GRANT, TokenProvider, decode_jwt_expiry
from bookshelf._core.client import BookshelfClient
from bookshelf._core.credentials import CredentialKind, StoredCredentials, default_store
from bookshelf._core.resolution import (
    NEWER_STORE_REMEDY,
    CredentialSource,
    ResolvedCredential,
    resolve_credential,
)
from bookshelf._generated import models

CLAIM_GRANT = "urn:workos:agent-auth:grant-type:claim"

_AGENT_PLATFORM = "bookshelf-cli"

auth_app = command_group("Manage authentication for the Bookshelf API.")


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
        if default_store().read_only():
            raise CliError(
                f"{credentials.credentials_path()} was written by a newer bookshelf, "
                f"so this version cannot store a login in it. {NEWER_STORE_REMEDY}",
                exit_code=EXIT_USAGE,
            )
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


def _login_agent_anonymous(base: str, *, json_output: bool) -> None:
    with BookshelfClient(base, auth=None) as client:
        registration = client.register_agent_identity(
            models.AgentIdentityRequest(
                type=models.AgentRegistrationType.anonymous, agent_platform=_AGENT_PLATFORM
            )
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
    default_store().save_login(
        StoredCredentials(
            access_token=grant.access_token,
            api_url=base,
            kind=CredentialKind.AGENT,
            expires_at=expires_at,
            identity_assertion=assertion,
            assertion_expires_at=assertion_expires,
            subject=subject,
            claimed=False,
        )
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
                type=models.AgentRegistrationType.service_auth,
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
    default_store().save_login(
        StoredCredentials(
            access_token=grant.access_token,
            api_url=base,
            kind=CredentialKind.AGENT,
            expires_at=expires_at,
            identity_assertion=grant.identity_assertion,
            assertion_expires_at=grant.assertion_expires,
            subject=subject,
            organization_id=me.organization_id,
            claimed=True,
        )
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
    if described.claimed is not None:
        report["claimed"] = described.claimed
        if not described.claimed:
            report["reaches"] = "public"


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
    is_agent = me.id.startswith("agent:")
    if is_agent:
        report["kind"] = "agent"
    elif described.kind == "machine":
        report["kind"] = "machine"
    else:
        report["kind"] = "user"
    report["id"] = me.id if is_agent else (me.email or me.id)
    report["organization_id"] = me.organization_id
    report["permissions"] = me.permissions or []
    if is_agent:
        claimed = me.organization_id is not None
        report["claimed"] = claimed
        if not claimed:
            report["reaches"] = "public"
    report["expires_at"] = iso(described.expires_at)


def _rejection_reason(credential: ResolvedCredential) -> str:
    """Say why a credential was likely refused, from what can be read off it locally."""
    expires_at = credential.describe().expires_at
    if expires_at is not None and expires_at <= datetime.now(UTC):
        return f"it expired at {iso(expires_at)}"
    token = os.environ.get("BOOKSHELF_TOKEN", "")
    from_env = credential.source is CredentialSource.ENV_TOKEN
    if from_env and not token.startswith("bsat_") and decode_jwt_expiry(token) is None:
        return "it is malformed, as it is neither a bsat_ agent token nor a JWT"
    return "it is revoked, or issued for another deployment"


@auth_app.command("logout")
def auth_logout(
    all_deployments: bool = typer.Option(
        False, "--all", help="Clear every stored identity for every deployment."
    ),
    no_revoke: bool = typer.Option(
        False, "--no-revoke", help="Skip server-side revocation and only clear local state."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the outcome as JSON."),
) -> None:
    """Revoke and clear stored credentials. Local state is cleared even when revocation fails."""
    with command_errors():
        base = None if all_deployments else base_url()
        store = default_store()
        records = [record for record in store.records() if base is None or record.api_url == base]
        cleared = {record.api_url for record in records}
        if not cleared:
            note("Not logged in." if base is None else f"Not logged in to {base}.")
            if json_output:
                emit_json({"cleared": [], "revoked": [], "revocation_failed": []})
            return

        # Cleared first, so a store this version cannot write is refused before anything is revoked.
        store.clear(base)
        revoked: list[str] = []
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
                revoked.append(record.api_url)
            except errors.BookshelfError:
                failed.append(record.api_url)

        for deployment in sorted(cleared):
            note(f"Cleared credentials for {deployment}")
        if json_output:
            emit_json(
                {
                    "cleared": sorted(cleared),
                    "revoked": sorted(set(revoked)),
                    "revocation_failed": sorted(set(failed)),
                }
            )

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
        store = default_store()
        records = store.records()
        active = store.active_kinds()
        # This version never refreshes a token from a newer store, so expiry is the end of it.
        refreshable = not store.read_only()
        now = datetime.now(UTC)
        if not records:
            note(
                "No stored identities. Run 'bookshelf auth login' to add one."
                if refreshable
                else f"No stored identities this version can read. {NEWER_STORE_REMEDY}"
            )
            return
        emit_payloads(
            (
                {
                    "kind": str(record.kind),
                    "id": record.subject,
                    "api_url": record.api_url,
                    "active": active.get(record.api_url) == record.kind,
                    "expired": record.expires_at is not None and record.expires_at <= now,
                    "needs_login": _spent(record, now, refreshable=refreshable),
                    "claimed": record.claimed,
                    "expires_at": iso(record.expires_at),
                    "assertion_expires_at": iso(record.assertion_expires_at),
                }
                for record in records
            ),
            json_output=json_output,
        )


def _spent(record: StoredCredentials, now: datetime, *, refreshable: bool) -> bool:
    """Say whether a record is past use without a fresh login: its token expired with nothing to renew it."""
    if record.expires_at is None or record.expires_at > now:
        return False
    if not refreshable:
        return True
    if record.refresh_token is not None:
        return False
    if record.kind is CredentialKind.AGENT and record.identity_assertion is not None:
        return record.assertion_expires_at is not None and record.assertion_expires_at <= now
    return True


@auth_app.command("switch")
def auth_switch(
    identity: str = typer.Argument(help="The identity to make active, as shown by 'auth list'."),
    json_output: bool = typer.Option(False, "--json", help="Emit the identity as JSON."),
) -> None:
    """Make a stored identity active without re-authenticating."""
    with command_errors():
        store = default_store()
        records = [record for record in store.records() if record.subject == identity]
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
        store.set_active(record.api_url, record.kind)
        note(f"Switched to {identity} ({record.api_url})")
        if json_output:
            emit_json({"kind": str(record.kind), "id": identity, "api_url": record.api_url})


__all__ = ["auth_app"]
