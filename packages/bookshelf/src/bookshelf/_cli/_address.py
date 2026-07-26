"""The one-string address grammar: ``volume[@version[_eNNN]][/entry]``.

Omitting the edition means the latest published edition,
and omitting the version means the latest published version.
The segment after the slash is an Entry's ``name_in_book``.
Parsing failures are a usage error and never reach the API.
"""

import re
from dataclasses import dataclass

from bookshelf._cli._runtime import EXIT_USAGE, CliError

_ADDRESS_PATTERN = re.compile(
    r"^(?P<volume>[^@/\s]+)"
    r"(?:@(?P<version>[^/\s]+?)(?:_e(?P<edition>\d{3}))?)?"
    r"(?:/(?P<entry>[^/\s]+))?$"
)


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
    """Parse an address string, raising a usage :class:`CliError` when malformed."""
    match = _ADDRESS_PATTERN.match(text)
    if match is None:
        raise CliError(
            f"malformed address {text!r}. "
            "Use volume[@version[_eNNN]][/file], e.g. primap-hist@1.0_e003/by_country.",
            exit_code=EXIT_USAGE,
        )
    edition = match.group("edition")
    return Address(
        volume=match.group("volume"),
        version=match.group("version"),
        edition=int(edition) if edition is not None else None,
        entry=match.group("entry"),
    )


__all__ = ["Address", "parse_address"]
