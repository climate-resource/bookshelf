"""Fetch the OIDC token a GitHub Actions job can mint for itself.

The job needs the ``id-token: write`` permission,
which is what makes the runtime set the two request variables read here.
"""

import os

import httpx

from bookshelf._core import errors

REQUEST_URL_VAR = "ACTIONS_ID_TOKEN_REQUEST_URL"
REQUEST_TOKEN_VAR = "ACTIONS_ID_TOKEN_REQUEST_TOKEN"


class ActionsTokenError(errors.AuthConfigurationError):
    """The Actions runtime did not hand over an OIDC token."""


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
    url = os.environ.get(REQUEST_URL_VAR)
    bearer = os.environ.get(REQUEST_TOKEN_VAR)
    if not url or not bearer:
        raise ActionsTokenError(
            f"${REQUEST_URL_VAR} and ${REQUEST_TOKEN_VAR} are not set. "
            "Run inside a GitHub Actions job with the 'id-token: write' permission."
        )
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(
                httpx.URL(url).copy_merge_params({"audience": audience}),
                headers={"Authorization": f"bearer {bearer}"},
            )
    except httpx.HTTPError as exc:
        raise errors.TransportError(f"could not reach the Actions token endpoint: {exc}") from exc
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


__all__ = ["ActionsTokenError", "fetch_actions_token"]
