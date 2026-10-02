# Addressing

Published data is named in one of two spellings:

- An **address**, `volume[@version[_eNNN]][/entry]`, which the CLI takes.
- A **reference**, `bookshelf://volume/version[_eNNN][/entry]`, which a recipe takes.
  `bookshelf show` accepts one too.

Both name the same things and follow the same rules for each part.

## Examples

| Address                            | Reference                                     | Names                                       |
| ---------------------------------- | --------------------------------------------- | ------------------------------------------- |
| `primap-hist`                      |                                               | the volume                                  |
| `primap-hist/by_country`           |                                               | that entry in the newest published book     |
| `primap-hist@v2.6`                 | `bookshelf://primap-hist/v2.6`                | the newest published edition of `v2.6`      |
| `primap-hist@v2.6_e002`            | `bookshelf://primap-hist/v2.6_e002`           | edition 2 of `v2.6`, whatever its status    |
| `primap-hist@v2.6_e002/by_country` | `bookshelf://primap-hist/v2.6_e002/by_country` | one entry of that edition                   |

Leaving the edition off means the newest published edition,
and leaving the version off as well means the newest published version.
Only a named edition reaches a draft.
A reference always names at least a version.
A recipe that wants the same bytes every time names the edition too.

`bookshelf://sha256/<hex>` names a file by the digest of its bytes rather than by where it sits in a book.
`bookshelf upload` returns one, and a recipe can declare it.
It is not an address, so `bookshelf show` refuses it.

## The parts

**Volume.**
ASCII letters, digits, `_` and `-`, at most 100 characters.
`latest` is reserved, in any case, for the latest-release link.

**Version.**
The upstream data version, as the upstream source writes it.
It starts with an ASCII letter or digit, then uses letters, digits, `.`, `_`, `+` and `-`,
at most 50 characters.
It must not end in `_e` followed by digits, because that is how an address spells the edition.
`v1.0_e2` is refused, where `v1.0-e2`, `v1.0_E2` and `v1_ebola` are fine.

**Edition.**
`_e` and the edition number, zero padded to at least three digits: `_e001`, `_e012`, `_e1000`.
`_e1` and `_e0001` are refused, so each edition has exactly one spelling.
The edition is the final `_e` and digits, so `ngfs@v4_scenario_e011` is edition 11 of `v4_scenario`.
The platform assigns it, so a producer never chooses one.

**Entry.**
The name a file has within its book.
A bundle names its entries in lower-case letters, digits, `.`, `_` and `-`,
starting with a letter or digit, at most 200 characters.

No part may be empty, `.` or `..`,
or hold whitespace, `@`, `/`, `?` or `#`.
A malformed address is a usage error (exit code 2), and is refused before any request is sent.

## Case

Names match exactly, case included,
so `PRIMAP-hist` and `primap-hist` are different volumes and `V2.6` is not `v2.6`.
The edition marker is a lower-case `_e`, and `_E001` is part of a version rather than an edition.
Two cases ignore case:

- `latest` is reserved whatever its case.
- Ordering versions to find the newest ignores case, so `V2.6` and `v2.6` sort together.

## Unicode

Every part is ASCII.
An address holding any other character names nothing that can exist.
The edition takes ASCII digits only,
so a lookalike digit such as `٠٠١` or `００１` is refused rather than read as `001`.
