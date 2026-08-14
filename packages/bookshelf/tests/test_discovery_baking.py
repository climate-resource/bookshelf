"""The editorial metadata a recipe resolves is baked onto each book at publish.

A book is a fixed thing.
Publishing a new version must never rewrite what an earlier version says about itself,
so every value the recipe resolved travels with the book that was published under it.
These tests assert on the wire payload,
because that is the only place the guarantee is actually kept.
"""

import json
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf.facade import AsyncBookshelf, Bookshelf
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.recipe import load_record_recipe
from bookshelf.publisher.record import _ACTIVE_RECORDING, _RecordingContext, setup
from bookshelf.publisher.replay import replay_bundle, replay_bundle_sync
from tests._replay import replay_response

BASE_URL = "https://bookshelf.test"

# Every field the recipe may default, so an inheriting book has something to inherit for each one of them.
_DEFAULT_DISCOVERY = {
    "title": "PRIMAP-hist",
    "publisher": "Potsdam Institute for Climate Impact Research",
    "publisher_url": "https://example.invalid/pik",
    "citation": "Guetschow et al. (2024)",
    "homepage_url": "https://example.invalid/primap",
    "documentation_url": "https://example.invalid/docs",
    "methodology_url": "https://example.invalid/method",
    "repository_url": "https://example.invalid/repo",
    "release_url": "https://example.invalid/release",
    "license_url": "https://example.invalid/licence",
    "intended_uses": "National inventory comparison.",
    "limitations": "Third-party gap filling is modelled.",
    "doi": "10.5281/zenodo.10006301",
    "release_date": "2023-09-13",
    "description": "A defaulted description.",
}

# The recipe field names that the API carries inside its nested ``discovery`` object,
# paired with the name it gives each one.
_WIRE_DISCOVERY_NAMES = {
    name: ("source_release_date" if name == "release_date" else name) for name in _DEFAULT_DISCOVERY
}

# The facts the platform computes per resource and rolls up.
# A producer never declares them, so they must never appear on a draft request.
_COMPUTED_FIELDS = (
    "spatial_coverage",
    "temporal_coverage",
    "variables",
    "units",
    "scenarios",
    "frequency",
)

# The facts that belong to the long-lived volume rather than to any one book.
_VOLUME_ONLY_FIELDS = (
    "maintainers",
    "keywords",
    "update_cadence",
    "deprecated",
    "superseded_by",
    "deprecation_note",
)


def _defaults_discovery_block() -> str:
    """Render the recipe's discovery defaults as YAML, flat under ``defaults:``."""
    lines = "\n".join(f"  {name}: {value}" for name, value in _DEFAULT_DISCOVERY.items())
    return lines + "\n  authors:\n    - name: Ada Lovelace\n      email: ada@example.com\n"


_RECIPE = f"""\
volume:
  name: primap-hist
  maintainers:
    - name: Jared Lewis
      email: jared@example.com
  keywords: [ghg, national]
  update_cadence: annual
defaults:
{_defaults_discovery_block()}build:
  notebook: build.py
books:
  - version: "v2.6"
    license: CC-BY-NC
  - version: "v2.7"
    license: CC-BY
    publisher: Climate Resource
    authors:
      - name: Jared Lewis
        email: jared@example.com
"""


def _write(tmp_path: Path, text: str) -> Path:
    """Write a recipe verbatim and return its path."""
    path = tmp_path / "bookshelf.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


@contextmanager
def _recording(recipe_path: Path, bundle: Bundle, version: str) -> Iterator[None]:
    """Enter a recording context for one version, the way ``run_record`` does."""
    recipe = load_record_recipe(recipe_path)
    context = _RecordingContext(
        recipe=recipe,
        resolved=recipe.resolve(version),
        bundle=bundle,
    )
    token = _ACTIVE_RECORDING.set(context)
    try:
        yield
    finally:
        _ACTIVE_RECORDING.reset(token)
        if context.bookshelf is not None:
            context.bookshelf.close()


def _record(recipe_path: Path, root: Path, version: str) -> Bundle:
    """Record one version's book framing into a fresh bundle."""
    bundle = Bundle(root)
    with _recording(recipe_path, bundle, version):
        setup()
    return bundle


def _transport(recorded: list[httpx.Request]) -> httpx.MockTransport:
    """Answer the replay route while keeping every request the run made."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json=replay_response(resource_count=0))

    return httpx.MockTransport(handler)


def _publish(bundle: Bundle, recorded: list[httpx.Request] | None = None) -> dict[str, Any]:
    """Replay a recorded bundle and return the book framing it sent."""
    seen = recorded if recorded is not None else []
    with Bookshelf(BASE_URL, auth=None, transport=_transport(seen)) as client:
        replay_bundle_sync(bundle, client)
    return json.loads(seen[-1].content)["book"]  # type: ignore[no-any-return]


def _record_and_publish(
    recipe_path: Path,
    root: Path,
    version: str,
    recorded: list[httpx.Request] | None = None,
) -> dict[str, Any]:
    """Record a version and replay it, returning the draft payload."""
    return _publish(_record(recipe_path, root, version), recorded)


def _volume_writes(recorded: list[httpx.Request]) -> list[tuple[str, str]]:
    """Return every request in a run that would write to a volume."""
    return [
        (request.method, request.url.path)
        for request in recorded
        if request.method != "GET" and request.url.path.startswith("/v1/volumes")
    ]


def test_publishing_a_later_version_does_not_rewrite_an_earlier_one(tmp_path: Path) -> None:
    """The whole point of baking: v2.6 keeps saying what v2.6 said, forever."""
    recipe = _write(tmp_path, _RECIPE)

    first = _record_and_publish(recipe, tmp_path / "b26", "v2.6")

    later: list[httpx.Request] = []
    second = _record_and_publish(recipe, tmp_path / "b27", "v2.7", later)

    assert first["discovery"]["publisher"] == _DEFAULT_DISCOVERY["publisher"]
    assert first["discovery"]["license"] == "CC-BY-NC"
    assert second["discovery"]["publisher"] == "Climate Resource"
    assert second["discovery"]["license"] == "CC-BY"

    # Publishing a book states what that book says. It never touches the volume.
    assert _volume_writes(later) == []

    again = _record_and_publish(recipe, tmp_path / "b26-again", "v2.6")
    assert again == first


def test_a_version_inherits_every_discovery_field_it_does_not_state(tmp_path: Path) -> None:
    recipe = _write(tmp_path, _RECIPE)

    payload = _record_and_publish(recipe, tmp_path / "bundle", "v2.6")

    expected: dict[str, Any] = {
        wire: _DEFAULT_DISCOVERY[name] for name, wire in _WIRE_DISCOVERY_NAMES.items()
    }
    expected["license"] = "CC-BY-NC"
    expected["authors"] = [{"name": "Ada Lovelace", "email": "ada@example.com"}]
    assert payload["discovery"] == expected


def test_an_override_changes_one_field_and_leaves_the_rest_inherited(tmp_path: Path) -> None:
    """Assert the whole payload, so dropping the inherited fields cannot pass."""
    recipe = _write(tmp_path, _RECIPE)

    payload = _record_and_publish(recipe, tmp_path / "bundle", "v2.7")

    expected: dict[str, Any] = {
        wire: _DEFAULT_DISCOVERY[name] for name, wire in _WIRE_DISCOVERY_NAMES.items()
    }
    expected["publisher"] = "Climate Resource"
    expected["license"] = "CC-BY"
    expected["authors"] = [{"name": "Jared Lewis", "email": "jared@example.com"}]
    assert payload["discovery"] == expected


def test_each_version_carries_the_licence_it_states(tmp_path: Path) -> None:
    recipe = _write(tmp_path, _RECIPE)

    older = _record_and_publish(recipe, tmp_path / "b26", "v2.6")
    newer = _record_and_publish(recipe, tmp_path / "b27", "v2.7")

    assert (older["discovery"]["license"], newer["discovery"]["license"]) == ("CC-BY-NC", "CC-BY")


def test_a_licence_declared_on_the_volume_is_rejected(tmp_path: Path) -> None:
    """There is no volume default to read, so declaring one has to fail loudly."""
    recipe = _write(
        tmp_path,
        """\
        volume:
          name: primap-hist
          license: CC-BY
        build:
          notebook: build.py
        books:
          - version: "v1.0.0"
            license: MIT
        """,
    )

    with pytest.raises(BookshelfError, match="license"):
        load_record_recipe(recipe)


def test_the_authors_a_version_states_reach_the_wire_and_the_bundle(tmp_path: Path) -> None:
    recipe = _write(tmp_path, _RECIPE)

    bundle = _record(recipe, tmp_path / "bundle", "v2.7")
    payload = _publish(bundle)

    stated = [{"name": "Jared Lewis", "email": "jared@example.com"}]
    assert payload["discovery"]["authors"] == stated
    # Replay reads the people off the bundle, so the two have to agree.
    assert bundle.manifest.book is not None
    assert bundle.manifest.book.authors == stated


def test_a_version_that_states_no_authors_inherits_the_volumes(tmp_path: Path) -> None:
    recipe = _write(tmp_path, _RECIPE)

    payload = _record_and_publish(recipe, tmp_path / "bundle", "v2.6")

    assert payload["discovery"]["authors"] == [{"name": "Ada Lovelace", "email": "ada@example.com"}]


def test_the_computed_fields_are_never_sent(tmp_path: Path) -> None:
    """The platform reads these off the bytes, so a declaration could only go stale."""
    recipe = _write(tmp_path, _RECIPE)

    payload = _record_and_publish(recipe, tmp_path / "bundle", "v2.7")

    # Assert on absence rather than on a null, because ``extra="forbid"`` would
    # otherwise hide the difference between omitted and sent as null.
    for name in _COMPUTED_FIELDS:
        assert name not in payload
        assert name not in payload["discovery"]


def test_the_volume_only_fields_are_never_sent_on_a_book(tmp_path: Path) -> None:
    recipe = _write(tmp_path, _RECIPE)

    payload = _record_and_publish(recipe, tmp_path / "bundle", "v2.7")

    for name in _VOLUME_ONLY_FIELDS:
        assert name not in payload
        assert name not in payload["discovery"]
    # The volume reaches the replay as the slug it is filed under, and nothing more.
    assert payload["volume"] == "primap-hist"
    assert "name" not in payload


@pytest.mark.parametrize(
    ("label", "version_body"),
    [
        ("absent", ""),
        ("declared empty", "    description:\n"),
    ],
)
def test_a_book_that_states_no_description_inherits_the_default(
    tmp_path: Path, label: str, version_body: str
) -> None:
    """An explicit YAML null reads the same as an absent key, and neither clears a default."""
    recipe = _write(
        tmp_path,
        f"""\
volume:
  name: primap-hist
defaults:
  description: National greenhouse gas emissions.
build:
  notebook: build.py
books:
  - version: "v1.0.0"
    license: MIT
{version_body}""",
    )

    payload = _record_and_publish(recipe, tmp_path / "bundle", "v1.0.0")

    assert payload["discovery"]["description"] == "National greenhouse gas emissions."


async def test_the_async_replay_sends_the_same_payload(tmp_path: Path) -> None:
    recipe = _write(tmp_path, _RECIPE)
    bundle = _record(recipe, tmp_path / "bundle", "v2.7")

    synchronous = _publish(bundle)

    recorded: list[httpx.Request] = []
    async with AsyncBookshelf(BASE_URL, auth=None, async_transport=_transport(recorded)) as client:
        await replay_bundle(bundle, client)

    assert json.loads(recorded[-1].content)["book"] == synchronous
