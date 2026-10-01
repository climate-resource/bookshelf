"""The one-string address grammar: ``volume[@version[_eNNN]][/entry]``.

Omitting the edition means the latest published edition,
and omitting the version means the latest published version.
The segment after the slash is an Entry's ``name_in_book``.
Parsing failures are a usage error and never reach the API.
"""

from dataclasses import dataclass

from bookshelf._cli._runtime import EXIT_USAGE, CliError
from bookshelf.publisher.reference import InvalidReferenceError, check_segment, split_coordinate


@dataclass(frozen=True, slots=True)
class Address:
    """A parsed address, with ``None`` marking each omitted segment."""

    volume: str
    version: str | None = None
    edition: int | None = None
    entry: str | None = None

    def __str__(self) -> str:
        text = self.volume
        if self.version is not None:
            text += f"@{self.version}"
            if self.edition is not None:
                text += f"_e{self.edition:03d}"
        if self.entry is not None:
            text += f"/{self.entry}"
        return text


def parse_address(text: str) -> Address:
    """Parse an address string, raising a usage :class:`CliError` when malformed.

    The edition follows the same rule as a ``bookshelf://`` reference.
    """
    head, has_entry, entry = text.partition("/")
    volume, has_version, coordinate = head.partition("@")
    try:
        check_segment(volume, "volume")
        version, edition = split_coordinate(coordinate) if has_version else (None, None)
        if has_entry:
            check_segment(entry, "file")
    except InvalidReferenceError as exc:
        raise CliError(
            f"malformed address {text!r}: {exc}. "
            "Use volume[@version[_eNNN]][/file], e.g. primap-hist@1.0_e003/by_country.",
            exit_code=EXIT_USAGE,
        ) from exc
    return Address(
        volume=volume,
        version=version,
        edition=edition,
        entry=entry if has_entry else None,
    )


__all__ = ["Address", "parse_address"]
