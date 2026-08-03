"""``bookshelf volume``: the collection lifecycle a first publish needs.

Drafting a book into a volume that does not exist fails,
so a new feedstock creates its volume here before it publishes.

Creation needs WRITE and deletion needs ADMIN,
so a credential that can make a volume may not be able to remove it.
"""

import json
from pathlib import Path
from typing import Any

import typer

from bookshelf._cli._runtime import (
    EXIT_USAGE,
    CliError,
    command_errors,
    emit,
    emit_json,
    field,
    iso,
)
from bookshelf._core.config import resolve_base_url
from bookshelf._generated import models
from bookshelf.facade import Bookshelf

volume_app = typer.Typer(help="Create, update and delete volumes.", no_args_is_help=True)


def _metadata(path: Path | None) -> dict[str, Any] | None:
    """Read a metadata document, treating an unreadable or non-object one as a usage error."""
    if path is None:
        return None
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CliError(
            f"cannot read the metadata at {path}: {exc}. "
            "Run 'bookshelf volume create --metadata PATH' naming a readable JSON file.",
            exit_code=EXIT_USAGE,
        ) from exc
    if not isinstance(document, dict):
        raise CliError(
            f"metadata at {path} is not a JSON object. "
            "Run 'bookshelf volume create --metadata PATH' naming a file holding one object.",
            exit_code=EXIT_USAGE,
        )
    return document


def _people(values: list[str]) -> list[dict[str, Any]] | None:
    """Parse repeated ``--author`` or ``--maintainer`` values, which carry a name and nothing else."""
    if not values:
        return None
    return [{"name": value} for value in values]


def _emit_volume(volume: models.VolumeResponse, *, json_output: bool) -> None:
    """Emit every field the command can set, so ``--json`` reads back what was sent."""
    authors = [person.name for person in volume.authors]
    maintainers = [person.name for person in volume.maintainers]
    if json_output:
        emit_json(
            {
                "id": volume.id,
                "name": volume.name,
                "license": volume.license,
                "description": volume.description,
                "citation": volume.citation,
                "authors": authors,
                "maintainers": maintainers,
                "metadata": volume.metadata,
                "created_at": iso(volume.created_at),
                "updated_at": iso(volume.updated_at),
            }
        )
        return
    lines = [
        volume.name,
        field("Id", volume.id),
        field("Licence", volume.license),
    ]
    if volume.description is not None:
        lines.append(field("Description", volume.description))
    if volume.citation is not None:
        lines.append(field("Citation", volume.citation))
    if authors:
        lines.append(field("Authors", ", ".join(authors)))
    if maintainers:
        lines.append(field("Maintainers", ", ".join(maintainers)))
    lines.append(field("Updated", iso(volume.updated_at) or "-"))
    emit("\n".join(lines))


@volume_app.command("create")
def volume_create(
    name: str = typer.Argument(help="Volume name, in alphanumerics, hyphens and underscores."),
    licence: str = typer.Option(..., "--licence", help="SPDX licence identifier."),
    description: str | None = typer.Option(None, "--description", help="Long-form description."),
    citation: str | None = typer.Option(None, "--citation", help="How to cite the dataset."),
    author: list[str] = typer.Option([], "--author", help="Author name. Repeatable."),
    maintainer: list[str] = typer.Option([], "--maintainer", help="Maintainer name. Repeatable."),
    metadata: Path | None = typer.Option(
        None, "--metadata", help="JSON file holding arbitrary volume metadata."
    ),
    api_url: str | None = typer.Option(None, "--api-url", help="Deployment to create in."),
    json_output: bool = typer.Option(False, "--json", help="Emit the volume as JSON."),
) -> None:
    """Create a volume, which a first publish into a new collection needs.

    Creating needs WRITE and deleting needs ADMIN,
    so you may not be able to delete what you create here.
    """
    with command_errors():
        document = _metadata(metadata)
        with Bookshelf(resolve_base_url(api_url)) as client:
            created = client.create_volume(
                name,
                license=licence,
                description=description,
                citation=citation,
                authors=_people(author),
                maintainers=_people(maintainer),
                metadata=document,
            )
        _emit_volume(created, json_output=json_output)


@volume_app.command("update")
def volume_update(
    name: str = typer.Argument(help="Volume to update."),
    description: str | None = typer.Option(None, "--description", help="Long-form description."),
    citation: str | None = typer.Option(None, "--citation", help="How to cite the dataset."),
    author: list[str] = typer.Option([], "--author", help="Author name. Repeatable."),
    maintainer: list[str] = typer.Option([], "--maintainer", help="Maintainer name. Repeatable."),
    metadata: Path | None = typer.Option(
        None, "--metadata", help="JSON file holding arbitrary volume metadata."
    ),
    api_url: str | None = typer.Option(None, "--api-url", help="Deployment to update in."),
    json_output: bool = typer.Option(False, "--json", help="Emit the volume as JSON."),
) -> None:
    """Update a volume's metadata. Each field given replaces what is there, and the licence is fixed."""
    with command_errors():
        document = _metadata(metadata)
        authors = _people(author)
        maintainers = _people(maintainer)
        given = (description, citation, document, authors, maintainers)
        if all(value is None for value in given):
            raise CliError(
                "update needs at least one field to change. "
                "Run 'bookshelf volume update NAME --description TEXT', or --help for the rest.",
                exit_code=EXIT_USAGE,
            )
        with Bookshelf(resolve_base_url(api_url)) as client:
            updated = client.update_volume(
                name,
                description=description,
                citation=citation,
                authors=authors,
                maintainers=maintainers,
                metadata=document,
            )
        _emit_volume(updated, json_output=json_output)


@volume_app.command("delete")
def volume_delete(
    name: str = typer.Argument(help="Volume to delete, with every book in it."),
    yes: bool = typer.Option(False, "--yes", help="Confirm the deletion, which is not reversible."),
    api_url: str | None = typer.Option(None, "--api-url", help="Deployment to delete from."),
    json_output: bool = typer.Option(False, "--json", help="Emit the outcome as JSON."),
) -> None:
    """Delete a volume and every book in it. This needs ADMIN, where creation needs WRITE."""
    with command_errors():
        if not yes:
            raise CliError(
                f"deleting {name!r} removes every book in it. "
                f"Run 'bookshelf volume delete {name} --yes' to confirm.",
                exit_code=EXIT_USAGE,
            )
        with Bookshelf(resolve_base_url(api_url)) as client:
            client.delete_volume(name)
        if json_output:
            emit_json({"outcome": "deleted", "volume": name})
            return
        emit(field("Deleted", name))


__all__ = ["volume_app"]
