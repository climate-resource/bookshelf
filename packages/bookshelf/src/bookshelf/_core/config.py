"""Base-URL resolution and the ``auth=`` sentinel for the unified client.

``auth=`` accepts a provider instance or a bare token string,
and an explicit ``auth=None`` stays unauthenticated.
Omitting it resolves the ambient credential, see :mod:`bookshelf._core.resolution`.
"""

import enum
import os
import warnings
from urllib.parse import urlparse

import httpx

from bookshelf._core.auth import StaticToken
from bookshelf._core.errors import ConfigurationError

PRODUCTION_API_URL = "https://bookshelf.climateresource.com.au"
PRODUCTION_API_HOST = urlparse(PRODUCTION_API_URL).hostname or ""
STAGING_API_URL = "https://bookshelf-staging.ovh.climateresource.com.au"

DEFAULT_API_URL = PRODUCTION_API_URL

AUTH_MODE_VAR = "BOOKSHELF_AUTH"
GITHUB_ACTIONS_AUTH_MODE = "github-actions"


class _Unset(enum.Enum):
    """Sentinel distinguishing an omitted ``auth=`` from an explicit ``auth=None``."""

    UNSET = enum.auto()


UNSET = _Unset.UNSET

AuthInput = httpx.Auth | str | None | _Unset


def resolve_base_url(base_url: str | None, *, source: str = "base_url") -> str:
    """Resolve the API base URL.

    The argument wins, then ``$BOOKSHELF_URL`` (canonical),
    then ``$BOOKSHELF_API_URL`` (accepted alias), then ``DEFAULT_API_URL``.
    The result never carries a trailing slash.
    A value that is not a plain http or https URL with a host raises :class:`ConfigurationError`,
    naming ``source`` when the argument supplied it, and the variable otherwise.
    ``$BOOKSHELF_REMOTE`` named the 0.4 S3 bucket and has no effect here, so setting it warns.
    """
    if os.environ.get("BOOKSHELF_REMOTE"):
        warnings.warn(
            "BOOKSHELF_REMOTE is ignored: bookshelf 1.x reads from the platform API, "
            "set BOOKSHELF_URL to choose a deployment",
            stacklevel=2,
        )
    candidates = (
        (base_url, source),
        (os.environ.get("BOOKSHELF_URL"), "$BOOKSHELF_URL"),
        (os.environ.get("BOOKSHELF_API_URL"), "$BOOKSHELF_API_URL"),
        (DEFAULT_API_URL, "the default"),
    )
    raw, origin = next((value, name) for value, name in candidates if value)
    resolved = raw.rstrip("/")
    problem = _base_url_problem(resolved)
    if problem is not None:
        raise ConfigurationError(f"{origin} {_redacted(resolved)!r} is not usable: {problem}")
    return resolved


def _base_url_problem(url: str) -> str | None:
    """Say what stops ``url`` serving as the API root, or ``None`` when it can."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        host = None
    if not host or parsed.scheme not in ("http", "https"):
        return "it needs an http:// or https:// URL with a host"
    if parsed.username is not None or parsed.password is not None:
        return "credentials in the URL are never sent, so drop the user@ part"
    if "?" in url:
        return "request paths are appended to it, so it cannot carry a ?query"
    if "#" in url:
        return "request paths are appended to it, so it cannot carry a #fragment"
    if parsed.path.rstrip("/").endswith("/v1"):
        return (
            f"give the deployment root without the trailing /v1, as in {url.removesuffix('/v1')!r}"
        )
    return None


def _redacted(url: str) -> str:
    """Hide a password, so a refused URL can be quoted back safely."""
    try:
        parsed = urlparse(url)
        password = parsed.password
    except ValueError:
        return url
    if password is None:
        return url
    return url.replace(f":{password}@", ":***@", 1)


def resolve_auth(auth: httpx.Auth | str | None) -> httpx.Auth | None:
    """Coerce an explicit ``auth=`` value into an ``httpx.Auth`` or ``None``."""
    if isinstance(auth, str):
        return StaticToken(auth)
    return auth


__all__ = [
    "AUTH_MODE_VAR",
    "DEFAULT_API_URL",
    "GITHUB_ACTIONS_AUTH_MODE",
    "PRODUCTION_API_HOST",
    "PRODUCTION_API_URL",
    "STAGING_API_URL",
    "UNSET",
    "AuthInput",
    "resolve_auth",
    "resolve_base_url",
]
