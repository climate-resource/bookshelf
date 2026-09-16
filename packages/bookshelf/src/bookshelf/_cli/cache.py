"""``bookshelf cache`` commands over the content cache the SDK fills."""

from datetime import UTC, datetime

import typer

from bookshelf._cli._runtime import (
    EXIT_USAGE,
    CliError,
    command_errors,
    emit,
    emit_payload,
    iso,
)
from bookshelf.cache import DEFAULT_MAX_BYTES, ContentCache, default_cache_dir

cache_app = typer.Typer(help="Manage the local content cache.", no_args_is_help=True)


def _iso_mtime(mtime: float | None) -> str | None:
    if mtime is None:
        return None
    return iso(datetime.fromtimestamp(mtime, tz=UTC))


@cache_app.command("info")
def cache_info(
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Show cache size, entry count, age range and the configured cap."""
    with command_errors():
        summary = ContentCache().summary()
        document = {
            "path": str(summary.path),
            "entries": summary.entries,
            "total_bytes": summary.total_bytes,
            "max_bytes": summary.max_bytes,
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
    with command_errors():
        cache = ContentCache()
        freed = cache.evict_lru(max_bytes=max_bytes)
        summary = cache.summary()
        emit_payload(
            {
                "bytes_freed": freed,
                "total_bytes": summary.total_bytes,
                "max_bytes": max_bytes,
            },
            json_output=json_output,
        )


@cache_app.command("clear")
def cache_clear(
    yes: bool = typer.Option(False, "--yes", help="Confirm removal of every cached entry."),
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Remove everything. Requires --yes, so a cache is never wiped by accident."""
    with command_errors():
        if not yes:
            raise CliError(
                "cache clear removes every entry and requires confirmation. "
                "Run 'bookshelf cache clear --yes'.",
                exit_code=EXIT_USAGE,
            )
        freed = ContentCache().clear()
        emit_payload({"bytes_freed": freed}, json_output=json_output)


@cache_app.command("path")
def cache_path() -> None:
    """Print the cache directory as a bare string, for shell interpolation."""
    emit(str(default_cache_dir()))


__all__ = ["cache_app"]
