"""Fixtures shared across the test suite."""

from pathlib import Path
from typing import Protocol
from uuid import uuid4

import pytest

from bookshelf._core.hashing import sha256_hex
from bookshelf.publisher.bundle import Bundle, BundleBook


class BundleFactory(Protocol):
    """Builds a bundle under ``tmp_path`` and returns it."""

    def __call__(
        self,
        *,
        published: bool = True,
        entries: int = 1,
        book: BundleBook | None = None,
    ) -> Bundle: ...


@pytest.fixture
def make_bundle(tmp_path: Path) -> BundleFactory:
    """Return a factory for a written bundle that satisfies the whole bundle contract.

    ``published``, ``entries`` and ``book`` each relax one part of it,
    so a test can name the single invariant it is about.
    """

    def factory(
        *,
        published: bool = True,
        entries: int = 1,
        book: BundleBook | None = None,
    ) -> Bundle:
        bundle = Bundle(tmp_path / "bundle")
        bundle.set_book(
            book
            if book is not None
            else BundleBook(volume="example", version="v1.0.0", visibility="public", license="MIT")
        )
        for index in range(entries):
            data = f"payload {index}".encode()
            resource = bundle.add_resource(
                data=data,
                hash_=sha256_hex(data),
                type_="document",
                tracking_id=uuid4(),
            )
            bundle.add_book_entry(name_in_book=f"entry-{index}", tracking_id=resource.tracking_id)
        if published:
            bundle.mark_book_published()
        bundle.write()
        return bundle

    return factory
