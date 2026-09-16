"""``bookshelf upload``: put a file on the bookshelf and get back the URI that names it.

A dataset that cannot be checked into a feedstock, because it is embargoed or too large,
is uploaded once and then declared in a recipe by digest.
The same resource can be used as inputs for different books if needed.
"""

from pathlib import Path

import typer

from bookshelf._cli._runtime import base_url, command_errors, emit_payload
from bookshelf._core.hashing import sha256_path
from bookshelf._core.names import flatten_to_resource_name
from bookshelf._generated import models
from bookshelf.facade import Bookshelf
from bookshelf.publisher.reference import DigestReference


def upload(
    file: Path = typer.Argument(
        help="File to upload.", exists=True, dir_okay=False, readable=True, resolve_path=True
    ),
    type: models.ResourceType = typer.Option(
        ..., "--type", help="Resource type the file registers under. Never inferred from the name."
    ),
    name: str | None = typer.Option(
        None, "--name", help="Resource name. Defaults to the file name, flattened."
    ),
    description: str | None = typer.Option(None, "--description", help="What the file is."),
    tag: list[str] = typer.Option([], "--tag", help="Catalogue tag. Repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Emit the outcome as JSON."),
) -> None:
    """Upload a file as a standalone input and print the bookshelf URI that names it.

    The URI is bookshelf://sha256/<hex>, which a recipe declares under resources: as its uri.
    The file is readable by your organisation alone.
    """
    with command_errors():
        content_hash = sha256_path(file)
        with Bookshelf(base_url()) as client:
            resource = client.register_file(
                type=type,
                path=file,
                hash=content_hash,
                name=name or flatten_to_resource_name(file.name),
                tags=tag,
                description=description,
            )
            # An aliased outcome reads the canonical row's type back, so it needs the client open.
            resource_type = resource.type
        uri = DigestReference(hash=content_hash).uri
        outcome = resource.registration_outcome
        assert outcome is not None, "a single registration always carries its outcome"
        size = file.stat().st_size
        emit_payload(
            {
                "uri": uri,
                "hash": content_hash,
                "tracking_id": str(resource.tracking_id),
                "outcome": outcome.status.value,
                "dedupe": outcome.dedupe,
                "name": resource.name,
                "type": resource_type.value,
                "size_bytes": size,
            },
            json_output=json_output,
        )


__all__ = ["upload"]
