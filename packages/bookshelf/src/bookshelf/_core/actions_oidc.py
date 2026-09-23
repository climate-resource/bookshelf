"""Fetch the OIDC token a GitHub Actions job can mint for itself.

The job needs the ``id-token: write`` permission,
which is what makes the runtime set the two request variables read here.

The audience decides what the token may do.
``bookshelf`` fills a preview and ``bookshelf-read`` reads the organisation's books,
and the API refuses each one on the other's routes.
"""

import os

import httpx

from bookshelf._core import errors

REQUEST_URL_VAR = "ACTIONS_ID_TOKEN_REQUEST_URL"
REQUEST_TOKEN_VAR = "ACTIONS_ID_TOKEN_REQUEST_TOKEN"

PREVIEW_AUDIENCE = "bookshelf"
READ_AUDIENCE = "bookshelf-read"


class ActionsTokenError(errors.AuthConfigurationError):
    """The Actions runtime did not hand over an OIDC token."""


def build_token_request(audience: str) -> httpx.Request:
    """Return the request asking the Actions runtime for a token minted for ``audience``.

    Raises :class:`ActionsTokenError` when the job cannot ask for one.
    """
    url = os.environ.get(REQUEST_URL_VAR)
    bearer = os.environ.get(REQUEST_TOKEN_VAR)
    if not url or not bearer:
        raise ActionsTokenError(
            f"${REQUEST_URL_VAR} and ${REQUEST_TOKEN_VAR} are not set. "
            "Run inside a GitHub Actions job with the 'id-token: write' permission."
        )
    try:
        request_url = httpx.URL(url).copy_merge_params({"audience": audience})
    except httpx.InvalidURL as exc:
        raise ActionsTokenError(f"${REQUEST_URL_VAR} is not a valid URL: {exc}") from exc
    return httpx.Request("GET", request_url, headers={"Authorization": f"bearer {bearer}"})


def token_from_response(response: httpx.Response) -> str:
    """Return the token an answer from the Actions runtime carries.

    Raises :class:`ActionsTokenError` when the runtime refused or answered without one.
    """
    if response.status_code != httpx.codes.OK:
        raise ActionsTokenError(
            f"the Actions token endpoint answered {response.status_code}: {response.text[:200]}"
        )
    try:
        token = response.json()["value"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ActionsTokenError("the Actions token endpoint answered without a token") from exc
    if not isinstance(token, str) or not token:
        raise ActionsTokenError("the Actions token endpoint answered without a token")
    return token


def fetch_actions_token(
    audience: str,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> str:
    """Return a GitHub Actions OIDC token minted for ``audience``.

    Raises :class:`ActionsTokenError` when the job cannot request one or the runtime refuses,
    and :class:`~bookshelf._core.errors.TransportError` when the runtime cannot be reached.
    """
    request = build_token_request(audience)
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.send(request)
    except httpx.HTTPError as exc:
        raise errors.TransportError(f"could not reach the Actions token endpoint: {exc}") from exc
    return token_from_response(response)


__all__ = [
    "PREVIEW_AUDIENCE",
    "READ_AUDIENCE",
    "ActionsTokenError",
    "build_token_request",
    "fetch_actions_token",
    "token_from_response",
]
