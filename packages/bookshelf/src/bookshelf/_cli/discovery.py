"""``bookshelf search`` and ``bookshelf show``: what exists, and what one address is."""

import re
from typing import Any

import typer

from bookshelf._cli._address import Address, parse_address
from bookshelf._cli._runtime import (
    EXIT_NOT_FOUND,
    CliError,
    command_errors,
    emit,
    emit_json,
    field,
    human_bytes,
    iso,
)
from bookshelf._core.client import BookshelfClient
from bookshelf._core.config import resolve_base_url
from bookshelf._generated import models

_LEADING_DIGITS = re.compile(r"^([0-9]+)(.*)$")
_ASCII_DIGITS = re.compile(r"^[0-9]+$")


def search(
    query: str | None = typer.Argument(
        None, help="Free text over name, title and summary. Optional."
    ),
    topic: list[str] = typer.Option([], "--topic", help="Topic the volume must carry."),
    keyword: list[str] = typer.Option([], "--keyword", help="Keyword the volume must carry."),
    region: list[str] = typer.Option([], "--region", help="Region the volume must cover."),
    publisher: str | None = typer.Option(None, "--publisher", help="Publisher organisation."),
    licence: str | None = typer.Option(None, "--licence", help="SPDX licence identifier."),
    coverage_year: int | None = typer.Option(
        None, "--coverage-year", help="Year the volume's data must cover."
    ),
    type_: str | None = typer.Option(None, "--type", help="Resource type the volume contains."),
    deprecated: bool | None = typer.Option(
        None,
        "--deprecated/--no-deprecated",
        help="Restrict to deprecated or to active volumes. Omitted means both.",
    ),
    limit: int = typer.Option(20, "--limit", min=1, max=1000, help="Maximum results."),
    offset: int = typer.Option(0, "--offset", min=0, help="Results to skip."),
    facets: bool = typer.Option(
        False, "--facets", help="List the valid filter values instead of searching."
    ),
    api_url: str | None = typer.Option(None, "--api-url", help="Deployment to search."),
    json_output: bool = typer.Option(False, "--json", help="One JSON object per result."),
) -> None:
    """Search volumes with free text and filters, which combine with AND."""
    with command_errors():
        with BookshelfClient(resolve_base_url(api_url)) as client:
            if facets:
                _emit_facets(client.get_catalogue_facets(), json_output)
                return
            volumes = client.list_volumes(
                q=query,
                topic=topic or None,
                keyword=keyword or None,
                region=region or None,
                publisher=publisher,
                license=licence,
                coverage_year=coverage_year,
                resource_type=type_,
                deprecated=deprecated,
                limit=limit,
                offset=offset,
            )
        for item in volumes.items:
            if json_output:
                emit_json(_volume_row(item))
            else:
                title = (
                    item.discovery.title.root if item.discovery and item.discovery.title else ""
                ) or ""
                latest = _latest_label(item.latest_version, item.latest_edition)
                emit(f"{item.name:<24} {title:<40} {latest}")


def _latest_label(version: str | None, edition: int | None) -> str:
    if version is None:
        return "-"
    if edition is None:
        return version
    return f"{version}_e{edition:03d}"


def _volume_row(item: models.VolumeListItem) -> dict[str, Any]:
    discovery = item.discovery
    return {
        "name": item.name,
        "title": discovery.title.root if discovery and discovery.title else None,
        "latest_version": item.latest_version,
        "latest_edition": item.latest_edition,
        "resource_types": item.resource_types or [],
        "topics": (discovery.topics if discovery else None) or [],
        "license": item.license,
    }


def _emit_facets(catalogue: models.VolumeFacets, json_output: bool) -> None:
    document = {
        "topics": catalogue.topics or [],
        "keywords": catalogue.keywords or [],
        "regions": catalogue.regions or [],
        "publishers": catalogue.publishers or [],
        "licences": catalogue.licenses or [],
        "types": catalogue.resource_types or [],
        "coverage_start_year": catalogue.coverage_start_year,
        "coverage_end_year": catalogue.coverage_end_year,
    }
    if json_output:
        emit_json(document)
        return
    for label in ("topics", "keywords", "regions", "publishers", "licences", "types"):
        values = document[label]
        assert isinstance(values, list)
        emit(field(label.rstrip("s") if label != "types" else "type", ", ".join(values)))
    if catalogue.coverage_start_year is not None or catalogue.coverage_end_year is not None:
        emit(
            field(
                "coverage",
                f"{catalogue.coverage_start_year or '?'}-{catalogue.coverage_end_year or '?'}",
            )
        )


def show(
    address: str = typer.Argument(help="volume[@version[_eNNN]][/file]"),
    api_url: str | None = typer.Option(None, "--api-url", help="Deployment to resolve against."),
    json_output: bool = typer.Option(False, "--json", help="Emit the description as JSON."),
) -> None:
    """Resolve one address and describe what is there, at whatever depth it is given."""
    with command_errors():
        parsed = parse_address(address)
        with BookshelfClient(resolve_base_url(api_url)) as client:
            if parsed.version is None and parsed.entry is None:
                _show_volume(client, parsed, json_output)
            else:
                book = _resolve_book(client, parsed)
                detail = client.get_book(book.id)
                label = f"{parsed.volume}@{detail.version}_e{detail.edition:03d}"
                if parsed.entry is None:
                    _show_book(detail, label, json_output)
                else:
                    _show_entry(detail, label, parsed.entry, json_output)


def _show_volume(client: BookshelfClient, parsed: Address, json_output: bool) -> None:
    volume = client.get_volume(parsed.volume)
    discovery = volume.discovery
    if json_output:
        emit_json(
            {
                "name": volume.name,
                "title": discovery.title.root if discovery and discovery.title else None,
                "publisher": (
                    discovery.publisher.root if discovery and discovery.publisher else None
                ),
                "license": volume.license,
                "topics": (discovery.topics if discovery else None) or [],
                "regions": (discovery.spatial_coverage if discovery else None) or [],
                "versions": [
                    {
                        "version": version.version,
                        "editions": [
                            {"edition": e.edition, "status": e.status} for e in version.editions
                        ],
                    }
                    for version in volume.versions
                ],
                "stats": {
                    "total_versions": volume.stats.total_versions,
                    "total_editions": volume.stats.total_editions,
                    "total_resources": volume.stats.total_resources,
                    "total_size_bytes": volume.stats.total_size_bytes,
                },
            }
        )
        return
    title = discovery.title.root if discovery and discovery.title else ""
    lines = [f"{volume.name}   {title}".rstrip()]
    if discovery and discovery.publisher:
        lines.append(field("Publisher", discovery.publisher.root))
    lines.append(field("Licence", volume.license))
    if discovery and discovery.topics:
        lines.append(field("Topics", ", ".join(discovery.topics)))
    if discovery and discovery.spatial_coverage:
        lines.append(field("Regions", ", ".join(discovery.spatial_coverage)))
    lines.append("")
    lines.append("Versions")
    for version in volume.versions:
        editions = "  ".join(
            f"e{e.edition:03d}" + (" (draft)" if e.status != "published" else "")
            for e in version.editions
        )
        lines.append(f"  {version.version:<7}{editions}")
    emit("\n".join(lines))


def _resolve_book(client: BookshelfClient, parsed: Address) -> models.BookListItem:
    """Resolve the address to one book, defaulting to the latest published."""
    books = client.list_books(
        volume=parsed.volume,
        version=parsed.version,
        status=None if parsed.edition is not None else "published",
        limit=1000,
    )
    candidates = books.items
    if parsed.edition is not None:
        candidates = [item for item in candidates if item.edition == parsed.edition]
    if not candidates:
        raise CliError(
            f"{parsed} does not resolve to a book. "
            f"Run 'bookshelf show {parsed.volume}' to see the published versions.",
            exit_code=EXIT_NOT_FOUND,
        )
    return max(candidates, key=_book_order)


def _book_order(item: models.BookListItem) -> tuple[Any, ...]:
    return (_version_key(item.version), item.edition)


def _identifier_key(identifier: str) -> tuple[int, int, str]:
    if _ASCII_DIGITS.fullmatch(identifier):
        return (0, int(identifier), "")
    return (1, 0, identifier.casefold())


def _version_key(version: str) -> tuple[Any, ...]:
    """Return a total SemVer-like ordering key for upstream version labels."""
    text = version.strip().removeprefix("v").split("+", 1)[0]
    core, _, prerelease = text.partition("-")
    identifiers = [part for part in prerelease.split(".") if part] if prerelease else []
    core_key: list[tuple[int, int, str]] = []
    for segment in core.split("."):
        match = _LEADING_DIGITS.match(segment)
        if match is None:
            core_key.append((1, 0, segment.casefold()))
            continue
        core_key.append((0, int(match.group(1)), ""))
        if match.group(2):
            identifiers.insert(0, match.group(2).lstrip("-."))

    while core_key and core_key[-1] == (0, 0, ""):
        core_key.pop()

    prerelease_key: tuple[Any, ...] = (
        (1,) if not identifiers else (0, tuple(_identifier_key(part) for part in identifiers))
    )
    return (tuple(core_key), prerelease_key)


def _show_book(detail: models.BookResponse, label: str, json_output: bool) -> None:
    resources = detail.resources or []
    if json_output:
        emit_json(
            {
                "address": label,
                "book_id": detail.id,
                "status": str(detail.status),
                "visibility": str(detail.visibility),
                "published_at": iso(detail.published_at),
                "resources": [
                    {
                        "name": resource.name,
                        "type": resource.type,
                        "format": resource.format,
                        "bytes": resource.size_bytes,
                        "content_hash": resource.content_hash,
                    }
                    for resource in resources
                ],
            }
        )
        return
    lines = [
        label,
        field("Status", str(detail.status)),
        field("Published", iso(detail.published_at) or "not published"),
        field("Visibility", str(detail.visibility)),
        "",
        "Resources",
    ]
    for resource in resources:
        size = human_bytes(resource.size_bytes) if resource.size_bytes is not None else "-"
        lines.append(
            f"  {resource.name:<20} {resource.type:<12} {size:<10} {resource.content_hash or ''}"
        )
    emit("\n".join(lines))


def _show_entry(detail: models.BookResponse, label: str, entry: str, json_output: bool) -> None:
    match = next(
        (resource for resource in detail.resources or [] if resource.name == entry),
        None,
    )
    if match is None:
        raise CliError(
            f"{label} has no file named {entry!r}. Run 'bookshelf show {label}' to list its files.",
            exit_code=EXIT_NOT_FOUND,
        )
    if json_output:
        emit_json(
            {
                "tracking_id": match.id,
                "name": match.name,
                "type": match.type,
                "format": match.format,
                "bytes": match.size_bytes,
                "content_hash": match.content_hash,
                "book": label,
            }
        )
        return
    size = human_bytes(match.size_bytes) if match.size_bytes is not None else "-"
    emit(
        "\n".join(
            [
                f"{label}/{match.name}",
                field("Type", match.type),
                field("Format", match.format or "-"),
                field("Size", size),
                field("Hash", match.content_hash or "-"),
            ]
        )
    )


__all__ = ["search", "show"]
