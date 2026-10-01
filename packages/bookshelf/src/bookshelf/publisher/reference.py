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
  exactly one entry, unless the recipe opts into all entries with ``whole_book: true``.
- ``bookshelf://primap-hist/v2.7`` leaves the edition to the platform, which answers with the
  newest. A recipe that wants the same bytes every time states the edition.

A file that sits in no book has no coordinate, so it is named by the digest of its bytes instead:
``bookshelf://sha256/<hex>``.
This is what ``bookshelf upload`` hands back.
A digest is scoped to the organisation that holds the bytes, so it resolves for its owner alone.
"""

import re
from dataclasses import dataclass
from typing import Self

from bookshelf._core.errors import BookshelfError

SCHEME = "bookshelf://"

# Unicode ``\d`` on purpose, so a lookalike digit is refused rather than read as part of the version.
_EDITION_SUFFIX_RE = re.compile(r"_e(?P<digits>\d*)$")
_FORBIDDEN_RE = re.compile(r"[\s@/?#]")
_DIGEST_RE = re.compile(r"^sha256/(?P<hex>[0-9a-fA-F]{64})$")
_DIGEST_LIKE_RE = re.compile(r"^sha256/[0-9a-fA-F]+(?:/.*)?$")


class InvalidReferenceError(BookshelfError, ValueError):
    """A ``bookshelf://`` reference is not one this client can parse."""


def _digest_hex(uri: str) -> str | None:
    """The lower-case hex of a digest reference, or ``None`` for any other string."""
    if not uri.startswith(SCHEME):
        return None
    matched = _DIGEST_RE.match(uri[len(SCHEME) :])
    return None if matched is None else matched["hex"].lower()


def check_segment(segment: str, label: str) -> str:
    """Return one volume, version or entry segment, raising :class:`InvalidReferenceError` when malformed."""
    if segment in ("", ".", ".."):
        raise InvalidReferenceError(f"{label} {segment!r} is not a name")
    if _FORBIDDEN_RE.search(segment) is not None:
        raise InvalidReferenceError(
            f"{label} {segment!r} holds whitespace or one of '@', '/', '?' and '#'"
        )
    return segment


def split_coordinate(coordinate: str) -> tuple[str, int | None]:
    """Split ``<version>[_eNNN]`` into the version and the edition it pins, if any.

    This is the one edition rule, shared by ``bookshelf://`` references and CLI addresses.
    The edition is written as the platform writes it: ASCII digits, zero padded to three, from 1.
    """
    check_segment(coordinate, "version")
    matched = _EDITION_SUFFIX_RE.search(coordinate)
    if matched is None:
        return coordinate, None
    version, digits = coordinate[: matched.start()], matched["digits"]
    # Comparing with the canonical spelling also refuses non-ASCII digits, which int() accepts.
    if not version or not digits or int(digits) < 1 or f"{int(digits):03d}" != digits:
        raise InvalidReferenceError(
            f"{coordinate!r} has a malformed edition. "
            "Write it as _eNNN with at least three digits, from _e001"
        )
    return version, int(digits)


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
        """Read a ``bookshelf://`` URI, raising :class:`InvalidReferenceError` naming the shape it takes.

        The check is structural, so a reference that parses is one a lookup can be attempted for.
        Whether the volume, the edition or the entry exists is a question only the platform answers.
        """
        if not uri.startswith(SCHEME):
            raise InvalidReferenceError(
                f"a bookshelf reference starts with {SCHEME!r}, got {uri!r}"
            )
        if _digest_hex(uri) is not None:
            raise InvalidReferenceError(
                f"{uri!r} names a resource by digest rather than by coordinate"
            )
        segments = uri[len(SCHEME) :].split("/")
        if len(segments) not in (2, 3) or not all(segments):
            raise InvalidReferenceError(
                f"{uri!r} is not a bookshelf reference. "
                f"Write {SCHEME}<volume>/<version>_e<edition>/<entry>, "
                "leaving the entry off where the book holds one or whole_book is true"
            )
        volume, coordinate, *rest = segments
        try:
            check_segment(volume, "volume")
            version, edition = split_coordinate(coordinate)
            entry = check_segment(rest[0], "entry") if rest else None
        except InvalidReferenceError as exc:
            raise InvalidReferenceError(f"{uri!r} is not a bookshelf reference: {exc}") from exc
        return cls(volume=volume, version=version, edition=edition, name_in_book=entry)


@dataclass(frozen=True, slots=True)
class DigestReference:
    """One resource the organisation holds, named by the digest of its bytes."""

    hash: str
    """The canonical ``sha256:<hex>`` digest, in lower case."""

    @property
    def uri(self) -> str:
        """The reference as it is written in a recipe."""
        return f"{SCHEME}sha256/{self.hash.removeprefix('sha256:')}"

    @classmethod
    def parse(cls, uri: str) -> Self:
        """Read a ``bookshelf://sha256/<hex>`` URI, raising :class:`InvalidReferenceError` otherwise."""
        if not uri.startswith(SCHEME):
            raise InvalidReferenceError(
                f"a bookshelf reference starts with {SCHEME!r}, got {uri!r}"
            )
        hex_ = _digest_hex(uri)
        if hex_ is None:
            raise InvalidReferenceError(
                f"{uri!r} is not a digest reference. Write {SCHEME}sha256/<64 hex characters>"
            )
        return cls(hash=f"sha256:{hex_}")


type Reference = BookshelfReference | DigestReference


def parse_reference(uri: str) -> Reference:
    """Read either reference shape, raising :class:`InvalidReferenceError` naming the one it falls short of.

    ``sha256`` followed by 64 hex characters is a digest.
    Hex of any other length after ``sha256/``, or hex followed by an entry,
    is a mistyped digest rather than a book,
    so it is refused instead of being looked up as a volume of that name.
    A volume called ``sha256`` stays reachable by any version that is not bare hex.
    """
    if _digest_hex(uri) is not None:
        return DigestReference.parse(uri)
    if uri.startswith(SCHEME) and _DIGEST_LIKE_RE.match(uri[len(SCHEME) :]) is not None:
        raise InvalidReferenceError(
            f"{uri!r} is not a digest reference. Write {SCHEME}sha256/<64 hex characters>"
        )
    return BookshelfReference.parse(uri)


def is_reference(uri: str) -> bool:
    """Say whether a declared URI names something on the bookshelf rather than something to fetch."""
    return uri.startswith(SCHEME)


__all__ = [
    "SCHEME",
    "BookshelfReference",
    "DigestReference",
    "InvalidReferenceError",
    "Reference",
    "check_segment",
    "is_reference",
    "parse_reference",
    "split_coordinate",
]
