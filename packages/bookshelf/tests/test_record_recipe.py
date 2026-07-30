"""Tests for the slim record recipe and the framing bookshelf.setup resolves from it."""

import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.record import (
    _ACTIVE_RECORDING,
    _RecordingContext,
    load_record_recipe,
    setup,
)


def _write_recipe(tmp_path: Path, extra: str = "") -> Path:
    """Write a minimal valid record recipe, plus any extra keys."""
    path = tmp_path / "bookshelf.yaml"
    path.write_text(
        textwrap.dedent(
            f"""\
            collection: my-dataset
            license: MIT
            authors:
              - name: Ada Lovelace
                email: ada@example.com
            notebook: build.py
            {extra}
            """
        )
    )
    return path


def test_visibility_is_optional(tmp_path: Path) -> None:
    assert load_record_recipe(_write_recipe(tmp_path)).visibility is None


@pytest.mark.parametrize("value", ["hidden", "org", "public"])
def test_every_visibility_tier_is_accepted(tmp_path: Path, value: str) -> None:
    recipe = load_record_recipe(_write_recipe(tmp_path, f"visibility: {value}"))

    assert recipe.visibility == value


def test_an_unknown_visibility_is_rejected_naming_the_allowed_values(tmp_path: Path) -> None:
    path = _write_recipe(tmp_path, "visibility: everyone")

    with pytest.raises(BookshelfError, match="visibility must be one of hidden, org, public"):
        load_record_recipe(path)


def test_direct_setup_without_a_collection_points_at_the_recorder() -> None:
    """The message names the cause and both ways forward, not just a missing argument."""
    with pytest.raises(BookshelfError) as excinfo:
        setup(version="v1.0.0")

    message = str(excinfo.value)
    assert "no active recording" in message
    assert "run_record" in message
    assert "collection=" in message


@contextmanager
def _recording(recipe_path: Path, bundle_path: Path) -> Iterator[None]:
    """Enter a recording context the way run_record does, without executing a notebook."""
    context = _RecordingContext(
        recipe=load_record_recipe(recipe_path),
        bundle=Bundle(bundle_path),
    )
    token = _ACTIVE_RECORDING.set(context)
    try:
        yield
    finally:
        _ACTIVE_RECORDING.reset(token)
        if context.bookshelf is not None:
            context.bookshelf.close()


def test_a_recorded_build_takes_its_visibility_from_the_recipe(tmp_path: Path) -> None:
    recipe = _write_recipe(tmp_path, "visibility: public")

    with _recording(recipe, tmp_path / "bundle"):
        _, book = setup(version="v1.0.0")

    assert book.metadata.visibility is models.Visibility.public


def test_an_explicit_argument_still_overrides_the_recipe(tmp_path: Path) -> None:
    recipe = _write_recipe(tmp_path, "visibility: public")

    with _recording(recipe, tmp_path / "bundle"):
        _, book = setup(version="v1.0.0", visibility="org")

    assert book.metadata.visibility is models.Visibility.org


def test_a_recipe_that_is_silent_leaves_the_book_hidden(tmp_path: Path) -> None:
    """Neither caller nor recipe saying anything must not widen a book."""
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        _, book = setup(version="v1.0.0")

    assert book.metadata.visibility is models.Visibility.hidden
