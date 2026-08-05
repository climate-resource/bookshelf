"""Tests for the slim record recipe and the framing bookshelf.setup resolves from it."""

import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models
from bookshelf._produce.types import RegisterItem
from bookshelf._produce.visibility import INHERIT
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.recipe import (
    RecordRecipe,
    load_record_recipe,
    resolve_book_visibility,
)
from bookshelf.publisher.record import (
    _ACTIVE_RECORDING,
    _RecordingContext,
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


@pytest.mark.parametrize("value", ["[a]", "{a: b}", "3"])
def test_a_visibility_that_is_not_a_string_stays_on_the_bookshelf_error_path(
    tmp_path: Path, value: str
) -> None:
    """An unhashable value must not escape as a raw TypeError from the membership test."""
    path = _write_recipe(tmp_path, f"visibility: {value}")

    with pytest.raises(BookshelfError, match="visibility must be one of"):
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


def test_an_explicit_empty_visibility_never_inherits_the_recipe(tmp_path: Path) -> None:
    """Invalid caller input must be rejected, not read as an omission.

    Falling through here would widen the book to the recipe's `public`,
    which is the one outcome this resolution must never produce by accident.
    """
    recipe = _write_recipe(tmp_path, "visibility: public")

    with _recording(recipe, tmp_path / "bundle"), pytest.raises(ValueError):
        setup(version="v1.0.0", visibility="")


def test_a_recipe_that_is_silent_leaves_the_book_hidden(tmp_path: Path) -> None:
    """Neither caller nor recipe saying anything must not widen a book."""
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        _, book = setup(version="v1.0.0")

    assert book.metadata.visibility is models.Visibility.hidden


# ----------------------------------------------------------------------
# The book's tier is the default for the resources the build records.
# ----------------------------------------------------------------------
def test_recorded_resources_take_the_books_visibility(tmp_path: Path) -> None:
    """A public book records public resources, so a generated feedstock can publish."""
    with _recording(_write_recipe(tmp_path, "visibility: public"), tmp_path / "bundle"):
        bs, _ = setup(version="v1.0.0")
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular")
            activity.register_many([RegisterItem(b"batched", type="tabular")])
            activity.register_external(type="tabular", uri="https://example.invalid/data.csv")
        bs.recording_sink.record_document(
            b"<html/>", logical_key="document/build.html", metadata={}
        )
        recorded = [r.visibility for r in bs.bundle.manifest.resources]

    assert recorded == ["public", "public", "public", "public"]


def test_a_recorded_resource_can_be_narrowed_below_the_book(tmp_path: Path) -> None:
    """Narrowing one member of a public book is a deliberate per-resource act."""
    with _recording(_write_recipe(tmp_path, "visibility: public"), tmp_path / "bundle"):
        bs, _ = setup(version="v1.0.0")
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"open", type="tabular")
            activity.register(b"embargoed", type="tabular", visibility="hidden")
        recorded = [r.visibility for r in bs.bundle.manifest.resources]

    assert recorded == ["public", "hidden"]


def test_a_hidden_book_still_records_hidden_resources(tmp_path: Path) -> None:
    """The pre-existing default is unchanged when nothing declares a wider tier."""
    with _recording(_write_recipe(tmp_path), tmp_path / "bundle"):
        bs, _ = setup(version="v1.0.0")
        with bs.activity(kind="build", code_ref="test") as activity:
            activity.register(b"data", type="tabular")
        recorded = [r.visibility for r in bs.bundle.manifest.resources]

    assert recorded == ["hidden"]


# ----------------------------------------------------------------------
# The precedence rule itself, reached directly rather than through a build.
# ----------------------------------------------------------------------
def _recipe(visibility: str | None) -> RecordRecipe:
    return RecordRecipe(
        collection="my-dataset",
        license="MIT",
        authors=(),
        visibility=visibility,
    )


def test_the_caller_outranks_the_recipe() -> None:
    resolved = resolve_book_visibility("org", recipe=_recipe("public"))

    assert resolved is models.Visibility.org


def test_the_recipe_applies_when_the_caller_says_nothing() -> None:
    resolved = resolve_book_visibility(None, recipe=_recipe("public"))

    assert resolved is models.Visibility.public


def test_silence_everywhere_resolves_to_hidden() -> None:
    assert resolve_book_visibility(None, recipe=_recipe(None)) is models.Visibility.hidden
    assert resolve_book_visibility(None) is models.Visibility.hidden


def test_an_empty_tier_is_rejected_rather_than_read_as_an_omission() -> None:
    """The one outcome this rule must never produce by accident is a silent widening."""
    with pytest.raises(ValueError):
        resolve_book_visibility("", recipe=_recipe("public"))


def test_an_omitted_tier_on_a_direct_draft_takes_the_sinks_default() -> None:
    """Drafting without a recipe inherits whatever the sink already defaults to."""
    resolved = resolve_book_visibility(INHERIT, default=models.Visibility.org)

    assert resolved is models.Visibility.org


def test_the_recipe_is_ignored_once_a_tier_is_declared_directly() -> None:
    """A recipe reaches the rule only through setup, never through a direct draft."""
    resolved = resolve_book_visibility(models.Visibility.hidden, recipe=_recipe("public"))

    assert resolved is models.Visibility.hidden
