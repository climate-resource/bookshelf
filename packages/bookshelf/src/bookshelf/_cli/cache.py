"""``bookshelf cache`` commands over the content cache the SDK fills."""

from datetime import UTC, datetime

import typer

from bookshelf._cli._runtime import (
    EXIT_USAGE,
    CliError,
    command_errors,
    emit,
    emit_json,
    field,
    human_bytes,
    iso,
    note,
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
        if json_output:
            emit_json(
                {
                    "path": str(summary.path),
                    "entries": summary.entries,
                    "total_bytes": summary.total_bytes,
                    "max_bytes": summary.max_bytes,
                    "oldest": _iso_mtime(summary.oldest_mtime),
                    "newest": _iso_mtime(summary.newest_mtime),
                }
            )
            return
        lines = [
            field("Path", str(summary.path)),
            field("Entries", str(summary.entries)),
            field(
                "Size",
                f"{human_bytes(summary.total_bytes)} of {human_bytes(summary.max_bytes)}",
            ),
        ]
        oldest = _iso_mtime(summary.oldest_mtime)
        if oldest is not None:
            lines.append(field("Oldest", oldest))
        newest = _iso_mtime(summary.newest_mtime)
        if newest is not None:
            lines.append(field("Newest", newest))
        emit("\n".join(lines))


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
        if json_output:
            emit_json(
                {
                    "bytes_freed": freed,
                    "total_bytes": summary.total_bytes,
                    "max_bytes": max_bytes,
                }
            )
            return
        emit(
            f"Evicted down to {human_bytes(max_bytes)}: freed {human_bytes(freed)}. "
            f"Cache now {human_bytes(summary.total_bytes)}."
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
        if json_output:
            emit_json({"bytes_freed": freed})
        else:
            note(f"Cleared cache, freed {human_bytes(freed)}.")


@cache_app.command("path")
def cache_path() -> None:
    """Print the cache directory as a bare string, for shell interpolation."""
    emit(str(default_cache_dir()))


__all__ = ["cache_app"]
