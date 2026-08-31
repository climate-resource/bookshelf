"""Git provenance and config-hash helpers for the activity surface."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID, uuid5

from bookshelf._core.errors import BookshelfError
from bookshelf._core.hashing import canonical_json_bytes, sha256_hex

# Fixed so a derived id is reproducible across processes and releases.
_ACTIVITY_NAMESPACE = UUID("6f2a1d3e-9c47-5b8a-a1f0-3d7e5c2b4a96")


def derive_code_ref() -> str:
    """Return ``<remote-url>@<sha>[+dirty]`` for the current git checkout.

    Raises :class:`~bookshelf._core.errors.BookshelfError` naming the unmet requirement,
    whether git cannot be run, this is not a usable repository, or it has no commits.
    The caller may pass ``code_ref=`` explicitly instead.
    """
    # gitpython raises at import time when the git binary is absent, and consuming a
    # book never needs git, so importing bookshelf must not depend on it.
    try:
        import git
    except ImportError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: git could not be run, "
            "because it is not installed or not on PATH. "
            "Pass code_ref= explicitly."
        ) from exc

    # Backstop, so nothing gitpython raises escapes as anything but a BookshelfError.
    try:
        return _derive_code_ref()
    except (git.GitError, OSError) as exc:
        raise BookshelfError(
            f"Cannot derive code_ref: git could not be queried ({exc}). Pass code_ref= explicitly."
        ) from exc


def _sanitise_remote_url(url: str) -> str:
    """Return ``url`` with any embedded credentials removed.

    A remote of the form ``https://user:token@host/path`` carries a credential that
    must never reach recorded provenance, so the userinfo component is dropped and
    the host, port and path are kept.
    Scp style remotes such as ``git@github.com:org/repo.git`` are returned unchanged,
    because there ``git`` is a fixed protocol user name rather than a credential.
    """
    parsed = urlsplit(url)
    if not parsed.scheme:
        return url
    if "@" not in parsed.netloc:
        return url
    if parsed.hostname is None:
        return url

    # hostname strips the brackets from an IPv6 literal, and a bare one cannot be told
    # apart from a host and port, so it has to be rebracketed.
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    return urlunsplit(parsed._replace(netloc=netloc))


def _derive_code_ref() -> str:
    """Read the code ref from the repository containing the working directory."""
    import git

    try:
        repo = git.Repo(Path.cwd(), search_parent_directories=True)
    except git.NoSuchPathError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: the working directory no longer exists. "
            "Pass code_ref= explicitly."
        ) from exc
    except git.InvalidGitRepositoryError as exc:
        raise BookshelfError(
            "Cannot derive code_ref: not inside a git repository. "
            "Run from a clone, or pass code_ref= explicitly."
        ) from exc

    # gitpython reads refs and config in pure Python, so a repository git itself rejects reads as empty.
    # Running a real git command first makes that failure surface as itself.
    try:
        dirty = repo.is_dirty(untracked_files=True)
    except (git.GitCommandNotFound, OSError) as exc:
        # A git that is absent, or present but not executable, lands here.
        raise BookshelfError(
            f"Cannot derive code_ref: git could not be run ({exc}). Pass code_ref= explicitly."
        ) from exc
    except git.GitCommandError as exc:
        detail = str(exc.stderr or "").strip()
        said = f" git said: {detail}" if detail else ""
        raise BookshelfError(
            "Cannot derive code_ref: git refused to read this repository. "
            f"Pass code_ref= explicitly.{said}"
        ) from exc

    if repo.bare:
        raise BookshelfError(
            "Cannot derive code_ref: this repository is bare, so it has no working tree "
            "whose state can be recorded. "
            "Run from a normal clone, or pass code_ref= explicitly."
        )
    if "origin" not in {remote.name for remote in repo.remotes}:
        raise BookshelfError(
            "Cannot derive code_ref: this repository has no 'origin' remote, "
            "so the code has no address to record. "
            "Add one with 'git remote add origin <url>', or pass code_ref= explicitly."
        )
    if not repo.head.is_valid():
        raise BookshelfError(
            "Cannot derive code_ref: this repository has no commits, "
            "so there is no revision to record. "
            "Commit first, or pass code_ref= explicitly."
        )

    ref = f"{_sanitise_remote_url(repo.remotes.origin.url)}@{repo.head.commit.hexsha}"
    if dirty:
        ref += "+dirty"
    return ref


def canonical_config_hash(config: dict[str, Any]) -> str:
    """Return the canonical ``sha256:<hex>`` digest for ``config``.

    Uses the platform's plain bundle-hash canonicalisation: ``sort_keys=True,
    separators=(",",":")`` via :func:`~bookshelf._core.hashing.canonical_json_bytes`.
    This is intentionally distinct from ``lock.py``'s recipe canonicaliser,
    which additionally recurse-sorts list elements and drops ``None`` values
    for the recipe-compile flow. The two agree on all flat configs.
    """
    return sha256_hex(canonical_json_bytes(config))


# ``<remote>@<sha>[+dirty]``, where the remote may itself hold an ``@`` in the scp form.
_CODE_REF = re.compile(r"^(?P<remote>.+)@(?P<sha>[0-9a-f]{40})(?P<dirty>\+dirty)?$")
_SCP_REMOTE = re.compile(r"^[^/@]+@(?P<host>[^:/]+):(?P<path>.+)$")

# The path segment a forge puts between the repository and the revision.
_FORGE_BLOB_SEGMENT = {"github.com": "blob", "gitlab.com": "-/blob"}


def source_url(code_ref: str, relative_path: str) -> str | None:
    """Return the web address of a checked-in file at the revision ``code_ref`` names.

    A checked-in input is re-hosted by the platform,
    so this link is what still ties the stored bytes back to the repository they came from.

    Returns ``None`` rather than raising whenever no honest link can be built:
    a dirty tree, because the revision does not name the bytes that were read,
    an unrecognised forge, or a remote this cannot parse.
    The link is a convenience, so failing to derive one must never fail a build.
    """
    match = _CODE_REF.match(code_ref)
    if match is None or match.group("dirty"):
        return None
    host, path = _remote_parts(match.group("remote"))
    if host is None or path is None:
        return None
    segment = _FORGE_BLOB_SEGMENT.get(host.lower())
    if segment is None:
        return None
    quoted = quote(relative_path.strip("/"))
    return f"https://{host}/{path}/{segment}/{match.group('sha')}/{quoted}"


def committed_source_url(path: Path) -> str | None:
    """Return the web address of ``path`` at the revision its own repository sits on.

    The repository containing the file is what is read, not the working directory,
    so a recipe in a subdirectory links to the file where it actually lives.

    What is checked is this one file rather than the state of the whole clone.
    A link is honest when the committed bytes are the bytes that were read,
    and an unrelated edit elsewhere in the repository does not change that.

    Returns ``None`` rather than raising whenever no honest link can be built:
    a file git does not track, one whose working copy has moved away from the commit,
    a repository without an origin or a commit, or an unrecognised forge.
    The link is a convenience, so failing to derive one must never fail a build.
    """
    try:
        import git
    except ImportError:
        return None
    try:
        repo = git.Repo(path.parent, search_parent_directories=True)
        if repo.bare or repo.working_tree_dir is None:
            return None
        if "origin" not in {remote.name for remote in repo.remotes}:
            return None
        if not repo.head.is_valid():
            return None
        relative = path.resolve().relative_to(Path(repo.working_tree_dir).resolve())
        # A file git does not track is absent from the revision, so a link would 404.
        committed = repo.head.commit.tree / relative.as_posix()
        if committed.hexsha != repo.git.hash_object(str(path.resolve())):
            return None
        code_ref = f"{_sanitise_remote_url(repo.remotes.origin.url)}@{repo.head.commit.hexsha}"
    except (git.GitError, KeyError, OSError, ValueError):
        return None
    return source_url(code_ref, relative.as_posix())


def _remote_parts(remote: str) -> tuple[str | None, str | None]:
    """Split a git remote into its host and its ``owner/repo`` path."""
    scp = _SCP_REMOTE.match(remote)
    if scp is not None:
        host, path = scp.group("host"), scp.group("path")
    else:
        parsed = urlsplit(remote)
        if not parsed.hostname:
            return None, None
        host, path = parsed.hostname, parsed.path
    path = path.strip("/").removesuffix(".git")
    return (host, path) if host and path else (None, None)


def derive_activity_id(
    *,
    kind: str,
    code_ref: str,
    config_hash: str,
    parameters: dict[str, Any],
) -> UUID:
    """Return the activity id the same build always mints.

    The id names what the activity is rather than when it ran,
    so recording a build twice produces one manifest and replaying it finds one activity.
    ``runner`` is left out because the same build on a laptop and on CI is the same activity.
    """
    seed = canonical_json_bytes(
        {
            "kind": kind,
            "code_ref": code_ref,
            "config_hash": config_hash,
            "parameters": parameters,
        }
    )
    return uuid5(_ACTIVITY_NAMESPACE, seed.decode())


__all__ = [
    "canonical_config_hash",
    "committed_source_url",
    "derive_activity_id",
    "derive_code_ref",
    "source_url",
]
