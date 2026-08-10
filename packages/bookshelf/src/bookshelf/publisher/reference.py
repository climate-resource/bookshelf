"""The ``bookshelf://`` reference a recipe uses to build on published data.

A feedstock whose input is another feedstock's output names it by the coordinate an author
reads off the catalogue, rather than by the tracking id the platform assigned it.

A reference resolves to a resource the platform already holds.
Nothing is fetched from upstream and nothing new is catalogued,
so the lineage of the book being built points at the original resource
and the same bytes are never registered twice.

The shape is ``bookshelf://<volume>/<version>_e<edition>/<entry>``:

- ``bookshelf://primap-hist/v2.7_e002/by_country`` names one entry of one edition.
- ``bookshelf://primap-hist/v2.7_e002`` names the edition, and resolves only when it holds
  exactly one entry.
- ``bookshelf://primap-hist/v2.7`` leaves the edition to the platform, which answers with the
  newest. A recipe that wants the same bytes every time states the edition.
"""

import re
from dataclasses import dataclass
from typing import Self

SCHEME = "bookshelf://"

_EDITION_RE = re.compile(r"^(?P<version>.+)_e(?P<edition>\d+)$")


@dataclass(frozen=True, slots=True)
class BookshelfReference:
    """One published resource, named by coordinate.

    ``edition`` is ``None`` when the reference leaves the choice to the platform,
    and ``name_in_book`` is ``None`` when it names the book rather than an entry of it.
    Neither is filled in here, because both are answered by a lookup rather than by parsing.
    """

    volume: str
    version: str
    edition: int | None = None
    name_in_book: str | None = None

    @property
    def coordinate(self) -> str:
        """The version, with the edition when the reference pins one."""
        return self.version if self.edition is None else f"{self.version}_e{self.edition:03}"

    @property
    def uri(self) -> str:
        """The reference as it is written in a recipe."""
        book = f"{SCHEME}{self.volume}/{self.coordinate}"
        return book if self.name_in_book is None else f"{book}/{self.name_in_book}"

    @classmethod
    def parse(cls, uri: str) -> Self:
        """Read a ``bookshelf://`` URI, raising :class:`ValueError` naming the shape it takes.

        The check is structural, so a reference that parses is one a lookup can be attempted for.
        Whether the volume, the edition or the entry exists is a question only the platform answers.
        """
        if not uri.startswith(SCHEME):
            raise ValueError(f"a bookshelf reference starts with {SCHEME!r}, got {uri!r}")
        segments = uri[len(SCHEME) :].split("/")
        if len(segments) not in (2, 3) or not all(segments):
            raise ValueError(
                f"{uri!r} is not a bookshelf reference. "
                f"Write {SCHEME}<volume>/<version>_e<edition>/<entry>, "
                "leaving the entry off only where the book holds one"
            )
        volume, coordinate, *rest = segments
        matched = _EDITION_RE.match(coordinate)
        if matched is None:
            return cls(volume=volume, version=coordinate, name_in_book=rest[0] if rest else None)
        return cls(
            volume=volume,
            version=matched["version"],
            edition=int(matched["edition"]),
            name_in_book=rest[0] if rest else None,
        )


def is_reference(uri: str) -> bool:
    """Say whether a declared URI names something on the bookshelf rather than something to fetch."""
    return uri.startswith(SCHEME)


__all__ = ["SCHEME", "BookshelfReference", "is_reference"]
