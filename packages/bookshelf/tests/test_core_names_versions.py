"""One version ordering, shared by the SDK facade and the CLI.

The two used to disagree.
The facade split on ``[._-]`` and read a prerelease as an extra trailing segment,
which made ``1.0.0-rc1`` sort NEWER than ``1.0.0``.
The CLI implemented SemVer, where a prerelease sorts older than its release.
SemVer won, so these pin the semantics.
The two surfaces now share one ordering function rather than agreeing by luck.
"""

import httpx
import pytest

from bookshelf._cli import discovery
from bookshelf._cli._address import parse_address
from bookshelf._consume.lookup import book_order as sdk_order
from bookshelf._core.client import BookshelfClient
from bookshelf._core.names import version_key
from bookshelf._generated import models
from tests import _core_payloads as payloads


def _item(version: str, edition: int = 1) -> models.BookListItem:
    return models.BookListItem.model_construct(version=version, edition=edition)


def _order(versions: list[str]) -> list[str]:
    return [item.version for item in sorted((_item(v) for v in versions), key=sdk_order)]


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        pytest.param("1.0.0-rc1", "1.0.0", id="prerelease-before-release"),
        pytest.param("1.0.0-alpha", "1.0.0-rc1", id="alpha-before-rc"),
        pytest.param("1.0.0-rc.1", "1.0.0-rc.2", id="numeric-prerelease-identifiers"),
        pytest.param("2.9", "2.10", id="numeric-runs-not-text"),
        pytest.param("1.9.9", "1.10.0", id="minor-numeric-runs"),
        pytest.param("v1.2.3", "v1.3.0", id="v-prefix-is-ignored"),
    ],
)
def test_the_older_version_sorts_first(older: str, newer: str) -> None:
    assert version_key(older) < version_key(newer)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        pytest.param("1.0", "1.0.0", id="trailing-zeros"),
        pytest.param("1.0.0", "1.0.0.0", id="more-trailing-zeros"),
        pytest.param("1.0.0", "1.0.0+build1", id="build-metadata-is-dropped"),
        pytest.param("1.0.0-rc1", "1.0.0-RC1", id="case-is-folded"),
        pytest.param("1.2.3", "v1.2.3", id="v-prefix"),
        pytest.param("1.2.3", "  1.2.3  ", id="surrounding-space"),
    ],
)
def test_these_versions_are_the_same_release(left: str, right: str) -> None:
    assert version_key(left) == version_key(right)


def test_a_prerelease_run_sorts_in_full_order() -> None:
    assert _order(["1.0.0", "1.0.0-rc1", "1.0.0-alpha", "1.0.0-beta"]) == [
        "1.0.0-alpha",
        "1.0.0-beta",
        "1.0.0-rc1",
        "1.0.0",
    ]


def test_edition_breaks_a_version_tie() -> None:
    """Trailing-zero normalisation makes the versions equal, so edition decides."""
    books = [_item("1.0.0", edition=2), _item("1.0", edition=1)]
    assert [book.edition for book in sorted(books, key=sdk_order)] == [1, 2]


@pytest.mark.parametrize(
    "version",
    ["2024-01", "v1.2", "rev3", "", "   ", "20240101", "v2.7_e002", "abc.def", "-", "+"],
)
def test_a_non_semver_label_sorts_without_raising(version: str) -> None:
    """Version is the UPSTREAM data version, so it is not obliged to be SemVer."""
    key = version_key(version)

    assert isinstance(key, tuple)
    assert key == version_key(version), "the key must be a pure function of the label"


def test_non_semver_labels_mix_with_semver_ones() -> None:
    labels = ["2024-01", "rev3", "1.0.0", "", "v2.7_e002"]

    assert len(_order(labels)) == len(labels)


def test_a_date_style_label_orders_within_its_own_family() -> None:
    """SemVer reads the hyphen as a prerelease, which still orders dated labels correctly."""
    assert _order(["2024-03", "2024-01", "2024-02"]) == ["2024-01", "2024-02", "2024-03"]


def test_the_cli_resolves_the_latest_book_by_this_ordering() -> None:
    """The CLI used to keep its own copy of the key, which is how the two drifted."""
    scrambled = [("v2.10", 1), ("v2.9", 2), ("v10.0", 1), ("v2.9.1", 1)]
    items = [
        dict(payloads.book_list_item(status="published"), version=version, edition=edition)
        for version, edition in scrambled
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=dict(payloads.BOOK_LIST, items=items, total=len(items)))

    client = BookshelfClient(
        "https://bookshelf.test", auth=None, transport=httpx.MockTransport(handler)
    )
    chosen = discovery._resolve_book(client, parse_address("primap-hist"))

    assert (chosen.version, chosen.edition) == ("v10.0", 1)
