"""``bookshelf cache`` commands over the content cache the SDK fills."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime

import typer

from bookshelf._cli._runtime import (
    EXIT_USAGE,
    CliError,
    command_errors,
    command_group,
    emit,
    emit_json,
    emit_payload,
    iso,
)
from bookshelf.cache import DEFAULT_MAX_BYTES, ContentCache, default_cache_dir

cache_app = command_group("Manage the local content cache.")


@contextmanager
def _usable_cache() -> Generator[None]:
    """Turn a cache directory the OS refuses into a usage error naming the setting that chose it."""
    with command_errors():
        try:
            yield
        except OSError as exc:
            raise CliError(
                f"the cache directory {default_cache_dir()} is unusable ({exc.strerror}). "
                "Set BOOKSHELF_CACHE_DIR to a writable directory.",
                exit_code=EXIT_USAGE,
            ) from exc


def _iso_mtime(mtime: float | None) -> str | None:
    if mtime is None:
        return None
    return iso(datetime.fromtimestamp(mtime, tz=UTC))


@cache_app.command("info")
def cache_info(
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Show cache size, entry count, age range and the configured cap."""
    with _usable_cache():
        summary = ContentCache().summary()
        document = {
            "path": str(summary.path),
            "entries": summary.entries,
            "total_size_bytes": summary.total_bytes,
            "max_size_bytes": summary.max_bytes,
            "oldest": _iso_mtime(summary.oldest_mtime),
            "newest": _iso_mtime(summary.newest_mtime),
        }
        emit_payload(document, json_output=json_output)


@cache_app.command("prune")
def cache_prune(
    max_bytes: int = typer.Option(
        DEFAULT_MAX_BYTES, "--max-bytes", min=0, help="Cap to prune the cache down to."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Evict oldest entries until the cache fits the cap."""
    with _usable_cache():
        cache = ContentCache()
        freed = cache.evict_lru(max_bytes=max_bytes)
        summary = cache.summary()
        emit_payload(
            {
                "freed_size_bytes": freed,
                "total_size_bytes": summary.total_bytes,
                "max_size_bytes": max_bytes,
            },
            json_output=json_output,
        )


@cache_app.command("clear")
def cache_clear(
    yes: bool = typer.Option(False, "--yes", help="Confirm removal of every cached entry."),
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Remove everything. Requires --yes, so a cache is never wiped by accident."""
    with _usable_cache():
        if not yes:
            raise CliError(
                "cache clear removes every entry and requires confirmation. "
                "Run 'bookshelf cache clear --yes'.",
                exit_code=EXIT_USAGE,
            )
        freed = ContentCache().clear()
        emit_payload({"freed_size_bytes": freed}, json_output=json_output)


@cache_app.command("path")
def cache_path(
    json_output: bool = typer.Option(False, "--json", help="Emit the path as JSON."),
) -> None:
    """Print the cache directory as a bare string, for shell interpolation."""
    path = str(default_cache_dir())
    if json_output:
        emit_json({"path": path})
    else:
        emit(path)


__all__ = ["cache_app"]
