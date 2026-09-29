"""Every field a recipe declares reaches an outbound request, is withheld on purpose, or is a tracked gap.

The leaves are derived from the recipe models, so a field added later joins the guard without an edit.
Each leaf gets a unique sentinel, one recording is published against a mocked deployment,
and each sentinel is looked for among the values of every request body the run sent.
Values are matched rather than keys, because the wire renames some fields.
"""

import json
import re
import types
from collections.abc import Iterator
from datetime import date
from typing import Any, Union, get_args, get_origin

import httpx
import pytest
import yaml
from pydantic import BaseModel

from bookshelf.facade import Bookshelf
from bookshelf.publisher import recording as recording_module
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.recipe import DiscoveryFields, PersonSpec, VolumeSection, _ResourceFields
from bookshelf.publisher.record import run_record
from bookshelf.publisher.replay import replay_bundle_sync
from tests import _core_payloads as payloads
from tests._replay import BASE_URL, replay_response

_SECTIONS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("volume", VolumeSection),
    ("book", DiscoveryFields),
    ("resource", _ResourceFields),
)

# Identity and location rather than catalogue metadata.
_STRUCTURAL = {
    "volume.name",
    "resource.type",
    "resource.uri",
    "resource.path",
    "resource.sha256",
    "resource.whole_book",
}

# The wire checks ORCIDs against a pattern, so each section gets a distinct valid one.
_ORCIDS = {
    "volume": "0000-0000-0000-0001",
    "book": "0000-0000-0000-0002",
    "resource": "0000-0000-0000-0003",
}

NOT_SENT_ON_PURPOSE: dict[str, str] = {}  # leaf -> reason

_ISSUE_260 = "https://github.com/climate-resource/bookshelf/issues/260"
KNOWN_GAPS: dict[str, str] = {  # leaf -> issue URL
    "volume.maintainers.name": _ISSUE_260,
    "volume.maintainers.email": _ISSUE_260,
    "volume.maintainers.affiliation": _ISSUE_260,
    "volume.maintainers.orcid": _ISSUE_260,
    "volume.keywords": _ISSUE_260,
    "volume.update_cadence": _ISSUE_260,
    "volume.deprecated": _ISSUE_260,
    "volume.superseded_by": _ISSUE_260,
    "volume.deprecation_note": _ISSUE_260,
}


def _unwrap_optional(annotation: Any) -> Any:  # noqa: ANN401
    if get_origin(annotation) in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(members) == 1:
            return members[0]
    return annotation


def _person(section: str, leaf: str) -> tuple[dict[str, str], dict[str, str]]:
    """One sentinel person, and the leaf id each of its subfields is checked under."""
    person: dict[str, str] = {}
    leaves: dict[str, str] = {}
    for name, field in PersonSpec.model_fields.items():
        sub_leaf = f"{leaf}.{name}"
        if _unwrap_optional(field.annotation) is not str:
            raise TypeError(f"no sentinel for {sub_leaf}: {field.annotation}")
        person[name] = _ORCIDS[section] if name == "orcid" else f"sentinel-{sub_leaf}"
        leaves[sub_leaf] = person[name]
    return person, leaves


def _derive() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """The recipe values per section, and the sentinel each leaf is expected to send."""
    recipe: dict[str, dict[str, Any]] = {}
    leaves: dict[str, Any] = {}
    for section, model in _SECTIONS:
        values = recipe.setdefault(section, {})
        for name, field in model.model_fields.items():
            leaf = f"{section}.{name}"
            if leaf in _STRUCTURAL:
                continue
            annotation = _unwrap_optional(field.annotation)
            if annotation is str:
                values[name] = leaves[leaf] = f"sentinel-{leaf}"
            elif annotation == list[str]:
                values[name] = leaves[leaf] = [f"sentinel-{leaf}"]
            elif annotation is bool:
                values[name] = leaves[leaf] = True
            elif annotation is date:
                values[name] = leaves[leaf] = date(1901, 2, 3)
            elif annotation == list[PersonSpec]:
                person, person_leaves = _person(section, leaf)
                values[name] = [person]
                leaves.update(person_leaves)
            else:
                raise TypeError(f"no sentinel for {leaf}: {field.annotation}")
    return recipe, leaves


_RECIPE_VALUES, LEAVES = _derive()

_BUILD = """\
import bookshelf

bs, book = bookshelf.setup()
raw = bs.use("raw")
book.write("totals", raw.path.read_bytes(), used=[raw])
book.publish()
"""


def _needles(leaf: str, value: Any) -> list[tuple[str | None, Any]]:  # noqa: ANN401
    """The ``(key, value)`` pairs that show a leaf arrived, where a ``None`` key matches any key.

    A bare ``True`` would match any flag, so a boolean is only found under its own field name.
    """
    if isinstance(value, list):
        return [(None, item) for item in value]
    if isinstance(value, bool):
        return [(leaf.rsplit(".", 1)[-1], value)]
    if isinstance(value, date):
        return [(None, value.isoformat())]
    return [(None, value)]


def _walk(node: Any, key: str | None = None) -> Iterator[tuple[str | None, Any]]:  # noqa: ANN401
    if isinstance(node, dict):
        for child_key, child in node.items():
            yield from _walk(child, child_key)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, key)
    else:
        yield key, node


def _arrived(needle: tuple[str | None, Any], sent: set[tuple[str | None, Any]]) -> bool:
    key, value = needle
    if key is None:
        return any(sent_value == value for _, sent_value in sent)
    # Identity, because ``1 == True`` would let an integer flag stand in for the boolean.
    return any(sent_key == key and sent_value is value for sent_key, sent_value in sent)


@pytest.fixture(scope="module")
def sent(tmp_path_factory: pytest.TempPathFactory) -> set[tuple[str | None, Any]]:
    """Record and publish the sentinel recipe once, returning every JSON leaf any request carried."""
    root = tmp_path_factory.mktemp("wire-coverage")
    book = {
        **_RECIPE_VALUES["book"],
        "version": "v1.0.0",
        "license": "CC-BY-4.0",
        "resources": {
            "raw": {**_RECIPE_VALUES["resource"], "type": "tabular", "path": "inputs/raw.csv"}
        },
    }
    recipe = {
        "volume": {"name": "my-dataset", **_RECIPE_VALUES["volume"]},
        "build": {"notebook": "build.py"},
        "books": [book],
    }
    (root / "bookshelf.yaml").write_text(yaml.safe_dump(recipe), encoding="utf-8")
    (root / "build.py").write_text(_BUILD, encoding="utf-8")
    (root / "inputs").mkdir()
    (root / "inputs" / "raw.csv").write_text("region,value\nWorld,1\n", encoding="utf-8")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            recording_module, "derive_code_ref", lambda: "https://example.invalid/test@0"
        )
        run_record(
            build_path=None,
            recipe_path=root / "bookshelf.yaml",
            bundle_path=root / "bundle",
            version="v1.0.0",
            parameters=None,
            cwd=root,
        )

    recorded: list[httpx.Request] = []

    # Answers every path, so a fix that adds a request turns a gap red rather than crashing the run.
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        path = request.url.path
        if path == "/v1/resources/uploads":
            return httpx.Response(200, json=payloads.UPLOAD_EXISTS)
        if path == "/v1/bundles/replay":
            return httpx.Response(200, json=replay_response())
        return httpx.Response(200, json=payloads.VOLUME)

    with Bookshelf(BASE_URL, auth=None, transport=httpx.MockTransport(handler)) as client:
        replay_bundle_sync(Bundle.read(root / "bundle"), client)

    return {
        pair
        for request in recorded
        if request.headers.get("content-type", "").startswith("application/json")
        for pair in _walk(json.loads(request.content))
    }


def test_every_leaf_has_a_sentinel() -> None:
    assert LEAVES
    assert {"volume.keywords", "book.release_date", "resource.doi"} <= LEAVES.keys()


@pytest.mark.parametrize(
    "leaf", [leaf for leaf in LEAVES if leaf not in NOT_SENT_ON_PURPOSE and leaf not in KNOWN_GAPS]
)
def test_the_leaf_reaches_a_request(leaf: str, sent: set[tuple[str | None, Any]]) -> None:
    missing = [needle for needle in _needles(leaf, LEAVES[leaf]) if not _arrived(needle, sent)]

    assert not missing, f"{leaf} was never sent: {missing}"


@pytest.mark.parametrize("leaf", list(KNOWN_GAPS))
def test_a_known_gap_is_still_missing(leaf: str, sent: set[tuple[str | None, Any]]) -> None:
    """A fix that sends the field must also delete its entry from ``KNOWN_GAPS``."""
    arrived = [needle for needle in _needles(leaf, LEAVES[leaf]) if _arrived(needle, sent)]

    assert not arrived, f"{leaf} now reaches a request, so delete it from KNOWN_GAPS"


def test_the_allowlists_are_well_formed() -> None:
    issue = re.compile(
        r"^https://github\.com/climate-resource/(bookshelf|bookshelf-platform)/issues/\d+$"
    )

    assert all(issue.match(url) for url in KNOWN_GAPS.values())
    assert all(isinstance(reason, str) and reason for reason in NOT_SENT_ON_PURPOSE.values())
    assert not KNOWN_GAPS.keys() & NOT_SENT_ON_PURPOSE.keys()
    assert (KNOWN_GAPS.keys() | NOT_SENT_ON_PURPOSE.keys()) <= LEAVES.keys()
