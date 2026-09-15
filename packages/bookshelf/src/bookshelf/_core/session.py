"""Confirm a client holds a credential the API accepts, logging a person in when one is present.

Machine credentials (``$BOOKSHELF_TOKEN`` and the client-credentials exchange CI uses)
are verified but never replaced,
because nobody is there to answer a login prompt.
A missing or spent stored login starts the WorkOS login when a person can answer it:
a browser login from a local terminal with a browser, a device code otherwise.
Anywhere else it raises :class:`~bookshelf._core.errors.AuthenticationRequiredError`.
"""

import asyncio
import enum
import os
import sys
import webbrowser
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, nullcontext
from typing import TextIO

from bookshelf._core import config, credentials, oauth
from bookshelf._core.auth import AnonymousFallback
from bookshelf._core.client import BookshelfClient
from bookshelf._core.config import CredentialSource
from bookshelf._core.credentials import CredentialKind, StoredCredentials
from bookshelf._core.errors import AuthenticationError, AuthenticationRequiredError
from bookshelf._generated import models

_LOGIN_REMEDY = (
    "Run 'bookshelf auth login' in a terminal, "
    "or in CI set BOOKSHELF_CLIENT_ID, BOOKSHELF_CLIENT_SECRET and BOOKSHELF_TOKEN_URL."
)

_MACHINE_SOURCES = {
    CredentialSource.ENV_TOKEN: "$BOOKSHELF_TOKEN",
    CredentialSource.CLIENT_CREDENTIALS: "the client credentials in $BOOKSHELF_CLIENT_ID",
}


def _isatty(stream: TextIO | None) -> bool:
    try:
        return stream is not None and stream.isatty()
    except (AttributeError, ValueError):
        return False


def _in_notebook() -> bool:
    """Report whether this process is a Jupyter kernel."""
    ipython = sys.modules.get("IPython")
    shell = getattr(ipython, "get_ipython", lambda: None)() if ipython is not None else None
    return type(shell).__name__ == "ZMQInteractiveShell"


def is_interactive() -> bool:
    """Report whether a person is present to answer a login prompt.

    ``$CI`` wins over everything, because runners can allocate a pseudo terminal.
    """
    if os.environ.get("CI", "").strip().lower() not in ("", "0", "false"):
        return False
    return (_isatty(sys.stdin) and _isatty(sys.stderr)) or _in_notebook()


def _has_browser() -> bool:
    """Report whether a browser login can redirect back to this process."""
    if _in_notebook() or os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    try:
        browser = webbrowser.get()
    except webbrowser.Error:
        return False
    # A console browser such as lynx cannot run the WorkOS sign-in page.
    return type(browser) is not webbrowser.GenericBrowser


def _quiet_spent_login(client: BookshelfClient) -> AbstractContextManager[None]:
    """Drop the spent-login warning while checking, because a login is offered in its place."""
    return client.auth.quieted() if isinstance(client.auth, AnonymousFallback) else nullcontext()


def _say(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _show_auth_url(url: str) -> None:
    _say("Opening a browser to log in to Bookshelf. If it does not open, visit:")
    _say(f"  {url}")


def _show_device_code(flow: oauth.DeviceFlowInfo) -> None:
    _say(f"To log in to Bookshelf, visit {flow.verification_uri_complete}")
    _say(f"and confirm the code {flow.user_code}. Waiting for approval...")


def login_user(
    api_url: str,
    *,
    browser: bool,
    on_auth_url: Callable[[str], None] = _show_auth_url,
    on_device_code: Callable[[oauth.DeviceFlowInfo], None] = _show_device_code,
) -> tuple[models.UserResponse, StoredCredentials]:
    """Run the WorkOS user login, store the credential and make it active.

    Raises :class:`~bookshelf._core.oauth.OAuthError` when the flow fails.
    """
    if browser:
        token_data = oauth.authorization_code_flow(api_url=api_url, on_auth_url=on_auth_url)
    else:
        flow = oauth.start_device_flow(api_url=api_url)
        on_device_code(flow)
        token_data = oauth.poll_device_flow(flow, api_url=api_url)

    access_token = str(token_data["access_token"])
    refresh_token = token_data.get("refresh_token")
    with BookshelfClient(api_url, auth=access_token) as client:
        user = client.get_current_user()
    record = credentials.save_credentials(
        access_token,
        api_url=api_url,
        kind=CredentialKind.USER,
        refresh_token=str(refresh_token) if refresh_token else None,
        expires_at=credentials.expiry_from(token_data.get("expires_in")),
        subject=user.email,
        organization_id=user.organization_id,
    )
    return user, record


def _require_login_allowed(
    client: BookshelfClient, rejected: AuthenticationError | None, interactive: bool | None
) -> None:
    """Raise unless a rejected or absent credential may be replaced by an interactive login."""
    if not client.uses_ambient_auth:
        raise AuthenticationRequiredError(
            "This client was given its credential through auth=, and the API did not accept it."
            if client.auth is not None
            else "This client was created with auth=None, so it cannot authenticate."
        ) from rejected
    source, _ = config.resolve_ambient_credential(client.base_url)
    if source in _MACHINE_SOURCES:
        raise AuthenticationRequiredError(
            f"The API rejected {_MACHINE_SOURCES[source]}. Check it is current for {client.base_url}."
        ) from rejected
    if not (is_interactive() if interactive is None else interactive):
        what = "The stored login was rejected" if rejected else "No Bookshelf credential was found"
        raise AuthenticationRequiredError(
            f"{what} for {client.base_url}, and there is nobody here to log in. {_LOGIN_REMEDY}"
        ) from rejected


def _login_and_adopt(client: BookshelfClient) -> models.UserResponse:
    """Log a person in, then point the client at the new credential."""
    try:
        user, record = login_user(client.base_url, browser=_has_browser())
    except oauth.OAuthError as exc:
        raise AuthenticationRequiredError(f"Logging in to Bookshelf failed: {exc}") from exc
    client.set_auth(config.auth_from_stored(record))
    client.verified_user = user
    return user


class _Step(enum.Enum):
    """The I/O the authentication flow asks its driver to perform."""

    FETCH_USER = enum.auto()
    LOG_IN = enum.auto()


_Flow = Generator[_Step, models.UserResponse, models.UserResponse]


def _authentication_flow(client: BookshelfClient, interactive: bool | None) -> _Flow:
    """Decide how to confirm the client's identity, yielding each step that needs I/O.

    A rejected ``FETCH_USER`` is thrown back in as :class:`AuthenticationError`.
    """
    if client.verified_user is not None:
        return client.verified_user
    rejected: AuthenticationError | None = None
    if client.auth is not None:
        try:
            with _quiet_spent_login(client):
                client.verified_user = yield _Step.FETCH_USER
            return client.verified_user
        except AuthenticationError as exc:
            rejected = exc
    _require_login_allowed(client, rejected, interactive)
    return (yield _Step.LOG_IN)


def ensure_authenticated(
    client: BookshelfClient, *, interactive: bool | None = None
) -> models.UserResponse:
    """Return the identity the API accepts for ``client``, logging in first when allowed.

    ``interactive`` overrides the terminal and notebook detection.
    A confirmed identity is remembered on the client, so later calls send no request.
    """
    flow = _authentication_flow(client, interactive)
    try:
        step = next(flow)
        while True:
            try:
                if step is _Step.FETCH_USER:
                    result = client.get_current_user()
                else:
                    result = _login_and_adopt(client)
            except AuthenticationError as exc:
                step = flow.throw(exc)
            else:
                step = flow.send(result)
    except StopIteration as done:
        user: models.UserResponse = done.value
        return user


async def ensure_authenticated_async(
    client: BookshelfClient, *, interactive: bool | None = None
) -> models.UserResponse:
    """The asynchronous twin of :func:`ensure_authenticated`, with the login run off the loop."""
    flow = _authentication_flow(client, interactive)
    try:
        step = next(flow)
        while True:
            try:
                if step is _Step.FETCH_USER:
                    result = await client.get_current_user_async()
                else:
                    result = await asyncio.to_thread(_login_and_adopt, client)
            except AuthenticationError as exc:
                step = flow.throw(exc)
            else:
                step = flow.send(result)
    except StopIteration as done:
        user: models.UserResponse = done.value
        return user


def _chose_anonymous(client: BookshelfClient) -> bool:
    return client.auth is None and not client.uses_ambient_auth


def require_authentication(client: BookshelfClient) -> None:
    """Confirm the credential before a write, unless the caller chose ``auth=None``."""
    if not _chose_anonymous(client):
        ensure_authenticated(client)


async def require_authentication_async(client: BookshelfClient) -> None:
    """The asynchronous twin of :func:`require_authentication`."""
    if not _chose_anonymous(client):
        await ensure_authenticated_async(client)


__all__ = [
    "ensure_authenticated",
    "ensure_authenticated_async",
    "is_interactive",
    "login_user",
    "require_authentication",
    "require_authentication_async",
]
