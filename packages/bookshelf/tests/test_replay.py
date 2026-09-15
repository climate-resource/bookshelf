"""Replaying a recorded bundle through the one-call replay endpoint.

The request is the whole contract now:
names address the resources, order carries the lineage,
and the server settles convergence from what it receives.
"""

import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import polars as pl
import pytest
from matplotlib.figure import Figure

from bookshelf._core.client import BookshelfClient
from bookshelf._core.hashing import sha256_hex
from bookshelf._generated import models
from bookshelf.cache import ContentCache
from bookshelf.facade import AsyncBookshelf
from bookshelf.publisher.bundle import Bundle, BundleActivity, BundleBook, InvalidBundleError
from bookshelf.publisher.recording import RecordingSink
from bookshelf.publisher.replay import replay_bundle, replay_bundle_sync
from tests import _core_payloads as payloads
from tests._replay import BASE_URL, replay_client, replay_response, replayed

CONFIG_HASH = "sha256:" + "0" * 64
POINTER_HASH = "sha256:" + "a" * 64


def _activity() -> BundleActivity:
    return BundleActivity(
        activity_id="0197a000-0000-7000-8000-00000000a001",  # type: ignore[arg-type]
        kind="build",
        code_ref="https://example.invalid/repo@" + "0" * 40,
        config_hash=CONFIG_HASH,
    )


def _derived_bundle(root: Path) -> Bundle:
    """A pointer input and the managed output derived from it, in that order."""
    bundle = Bundle(root)
    bundle.set_book(
        BundleBook(volume="example", version="v1.0.0", visibility="public", license="MIT")
    )
    bundle.set_activity(_activity())
    bundle.add_pointer(
        external_uri="https://example.invalid/raw.csv",
        hash_=POINTER_HASH,
        type_="tabular",
        name="raw",
        generated=True,
    )
    data = b"derived payload"
    bundle.add_resource(
        data=data,
        hash_=sha256_hex(data),
        type_="tabular",
        name="derived",
        generated=True,
        used=["raw"],
    )
    bundle.add_book_entry(name="derived")
    bundle.mark_book_published()
    bundle.write()
    return bundle


def test_a_used_input_travels_as_the_name_of_an_earlier_resource(tmp_path: Path) -> None:
    bundle = _derived_bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    resources = replayed(recorded)["resources"]
    assert [resource["name"] for resource in resources] == ["raw", "derived"]
    assert resources[1]["used"] == ["raw"]


def test_a_used_digest_travels_as_the_bytes_the_platform_holds(tmp_path: Path) -> None:
    """An input the bundle does not carry has no name, so the request cites its digest."""
    upload = "sha256:" + "b" * 64
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(
        BundleBook(volume="example", version="v1.0.0", visibility="public", license="MIT")
    )
    bundle.set_activity(_activity())
    data = b"derived payload"
    bundle.add_resource(
        data=data,
        hash_=sha256_hex(data),
        type_="tabular",
        name="derived",
        generated=True,
        used_digests=[upload],
    )
    bundle.add_book_entry(name="derived")
    bundle.mark_book_published()
    bundle.write()
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    resources = replayed(recorded)["resources"]
    assert [resource["name"] for resource in resources] == ["derived"]
    assert resources[0]["used"] == [{"content_hash": upload}]


def test_a_used_digest_travels_after_the_names_alongside_it(tmp_path: Path) -> None:
    """Both citation forms reach the one field the request carries."""
    upload = "sha256:" + "b" * 64
    bundle = _derived_bundle(tmp_path / "bundle")
    bundle.manifest.resources[1].used_digests = [upload]
    bundle.write()
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    resources = replayed(recorded)["resources"]
    assert resources[1]["used"] == ["raw", {"content_hash": upload}]


def test_a_resource_consuming_one_the_bundle_records_later_is_refused(tmp_path: Path) -> None:
    """Ordering is the contract, so a forward reference fails here rather than as a 422."""
    bundle = Bundle(tmp_path / "bundle")
    data = b"derived payload"

    with pytest.raises(ValueError, match="does not record before it"):
        bundle.add_resource(
            data=data,
            hash_=sha256_hex(data),
            type_="tabular",
            name="derived",
            generated=True,
            used=["raw"],
        )


def test_a_name_recorded_twice_is_refused(tmp_path: Path) -> None:
    """One name addresses one resource, so a second claim on it is a recording error."""
    bundle = Bundle(tmp_path / "bundle")
    bundle.add_pointer(
        external_uri="https://example.invalid/raw.csv",
        hash_=POINTER_HASH,
        type_="tabular",
        name="raw",
    )

    with pytest.raises(ValueError, match="already recorded"):
        bundle.add_pointer(
            external_uri="https://example.invalid/other.csv",
            hash_=POINTER_HASH,
            type_="tabular",
            name="raw",
        )


def test_a_pointer_carries_its_target_and_no_storage_path(tmp_path: Path) -> None:
    """The platform must not re-host a pointer, so it is given nowhere to read it from."""
    bundle = _derived_bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    pointer, managed = replayed(recorded)["resources"]
    assert pointer["kind"] == "pointer"
    assert pointer["external_uri"] == "https://example.invalid/raw.csv"
    assert "storage_path" not in pointer
    assert "size_bytes" not in pointer
    assert managed["kind"] == "managed"
    assert managed["storage_path"] == "ingest/org_1/abc"
    assert managed["size_bytes"] == len(b"derived payload")


def test_a_resource_stating_no_discovery_sends_no_discovery_object(tmp_path: Path) -> None:
    """An omitted field must stay omitted, because the API refuses an explicit null on it."""
    bundle = _derived_bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    for resource in replayed(recorded)["resources"]:
        assert "discovery" not in resource


def test_a_resource_sends_only_the_discovery_fields_it_recorded(tmp_path: Path) -> None:
    """The unstated siblings of a stated field must not travel as nulls either."""
    bundle = Bundle(tmp_path / "bundle")
    data = b"described payload"
    bundle.add_resource(
        data=data,
        hash_=sha256_hex(data),
        type_="tabular",
        name="derived",
        discovery=models.ResourceDiscovery(description="What we made."),
    )
    bundle.write()
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    (resource,) = replayed(recorded)["resources"]
    assert resource["discovery"] == {"description": "What we made."}


def test_a_book_stating_no_discovery_sends_no_discovery_object(tmp_path: Path) -> None:
    """The book-level framing omits the same way a resource does."""
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(BundleBook(volume="example", version="v1.0.0"))
    data = b"derived payload"
    bundle.add_resource(data=data, hash_=sha256_hex(data), type_="tabular", name="derived")
    bundle.add_book_entry(name="derived")
    bundle.write()
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    assert "discovery" not in replayed(recorded)["book"]


def test_a_book_sends_the_discovery_it_states(tmp_path: Path) -> None:
    """A stated fact still travels, folded into the discovery object the API reads."""
    bundle = Bundle(tmp_path / "bundle")
    bundle.set_book(
        BundleBook(
            volume="example",
            version="v1.0.0",
            license="MIT",
            discovery={"title": "An example"},
        )
    )
    data = b"derived payload"
    bundle.add_resource(data=data, hash_=sha256_hex(data), type_="tabular", name="derived")
    bundle.add_book_entry(name="derived")
    bundle.write()
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    assert replayed(recorded)["book"]["discovery"] == {"title": "An example", "license": "MIT"}


def test_an_entry_without_a_data_dictionary_sends_none(tmp_path: Path) -> None:
    """Omitting the dictionary keeps an existing one, so the key must not travel as a null."""
    bundle = _derived_bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    (entry,) = replayed(recorded)["book"]["entries"]
    assert entry == {"name": "derived"}


def test_an_activity_without_a_runner_sends_no_runner(tmp_path: Path) -> None:
    bundle = _derived_bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    assert "runner" not in replayed(recorded)["activity"]


def test_the_managed_bytes_are_uploaded_before_the_replay(tmp_path: Path) -> None:
    bundle = _derived_bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    assert [request.url.path for request in recorded] == [
        "/v1/resources/uploads",
        "/v1/bundles/replay",
    ]


def test_the_recorded_activity_travels_under_its_own_id(tmp_path: Path) -> None:
    """Sending the id again is what stops a repeated replay minting duplicate edges."""
    bundle = _derived_bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    activity = replayed(recorded)["activity"]
    assert activity["activity_id"] == "0197a000-0000-7000-8000-00000000a001"
    assert activity["config_hash"] == CONFIG_HASH


def test_a_converged_replay_reports_what_the_server_settled(tmp_path: Path) -> None:
    bundle = _derived_bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []
    answered = replay_response(converged=True, resource_count=2, dedupe_hits=2, edition=5)

    with replay_client(recorded, response=answered) as client:
        response = replay_bundle_sync(bundle, client)

    assert response.converged is True
    assert response.dedupe_hits == 2
    assert response.book is not None
    assert response.book.edition == 5


def test_a_bundle_path_is_read_before_it_is_replayed(tmp_path: Path) -> None:
    """The usual publish workflow hands over a directory rather than a loaded bundle."""
    _derived_bundle(tmp_path / "bundle")
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(tmp_path / "bundle", client)

    assert [resource["name"] for resource in replayed(recorded)["resources"]] == ["raw", "derived"]


async def test_the_async_replay_sends_the_same_request(tmp_path: Path) -> None:
    bundle = _derived_bundle(tmp_path / "bundle")
    synchronous: list[httpx.Request] = []
    with replay_client(synchronous) as client:
        replay_bundle_sync(bundle, client)

    asynchronous: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asynchronous.append(request)
        if request.url.path == "/v1/resources/uploads":
            return httpx.Response(
                200, json={"already_exists": True, "storage_path": "ingest/org_1/abc"}
            )
        return httpx.Response(200, json=replay_response())

    async with AsyncBookshelf(
        BASE_URL, auth=None, async_transport=httpx.MockTransport(handler)
    ) as client:
        await replay_bundle(bundle, client)

    assert replayed(asynchronous) == replayed(synchronous)


def test_a_recorded_figure_replays_as_a_png_drawn_from_its_values(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    sink = RecordingSink(bundle, Mock(spec=BookshelfClient), ContentCache(tmp_path / "cache"))
    book = sink.draft_book("example", version="v1.0.0", license="MIT")
    fig = Figure()
    fig.add_subplot().plot([1.0, 2.0])
    book.write("fig", fig, type="figure", data=pl.DataFrame({"y": [1.0, 2.0]}))
    book.publish()
    bundle.write()
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    figure = next(
        resource for resource in replayed(recorded)["resources"] if resource["name"] == "fig"
    )
    assert (figure["type"], figure["format"]) == ("figure", "png")
    assert figure["used"] == ["fig-data"]
    uploads = [
        json.loads(request.content)
        for request in recorded
        if request.url.path == "/v1/resources/uploads"
    ]
    assert sorted(upload["content_type"] for upload in uploads) == [
        "application/vnd.apache.parquet",
        "image/png",
        "image/svg+xml",
    ]


def _figure_bundle(tmp_path: Path, obj: object) -> Bundle:
    """A published book holding one figure written from ``obj``."""
    bundle = Bundle(tmp_path / "bundle")
    sink = RecordingSink(bundle, Mock(spec=BookshelfClient), ContentCache(tmp_path / "cache"))
    book = sink.draft_book("example", version="v1.0.0", license="MIT")
    book.write("fig", obj, type="figure", alt_text="A line.")
    book.publish()
    bundle.write()
    return bundle


def _uploads(recorded: list[httpx.Request]) -> list[dict[str, object]]:
    return [
        json.loads(request.content)
        for request in recorded
        if request.url.path == "/v1/resources/uploads"
    ]


def test_a_recorded_figure_replays_with_its_svg_companion(tmp_path: Path) -> None:
    fig = Figure()
    fig.add_subplot().plot([1.0, 2.0])
    bundle = _figure_bundle(tmp_path, fig)
    (figure_record,) = bundle.manifest.resources
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    (figure,) = replayed(recorded)["resources"]
    assert figure["svg"] == {"storage_path": "ingest/org_1/abc", "hash": figure_record.svg_hash}
    uploads = _uploads(recorded)
    assert [upload["content_type"] for upload in uploads] == ["image/png", "image/svg+xml"]
    assert uploads[1]["hash"] == figure_record.svg_hash


def test_a_figure_without_an_svg_companion_sends_no_svg(tmp_path: Path) -> None:
    fig = Figure()
    fig.add_subplot().plot([1.0, 2.0])
    png = _figure_bundle(tmp_path / "source", fig)
    bundle = _figure_bundle(tmp_path, png.resource_bytes(png.manifest.resources[0]))
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    (figure,) = replayed(recorded)["resources"]
    assert "svg" not in figure
    assert [upload["content_type"] for upload in _uploads(recorded)] == ["image/png"]


async def test_the_async_replay_uploads_the_svg_companion_too(tmp_path: Path) -> None:
    fig = Figure()
    fig.add_subplot().plot([1.0, 2.0])
    bundle = _figure_bundle(tmp_path, fig)
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.url.path == "/v1/resources/uploads":
            return httpx.Response(200, json=payloads.UPLOAD_EXISTS)
        return httpx.Response(200, json=replay_response())

    async with AsyncBookshelf(
        BASE_URL, auth=None, async_transport=httpx.MockTransport(handler)
    ) as client:
        await replay_bundle(bundle, client)

    (figure,) = replayed(recorded)["resources"]
    assert figure["svg"]["hash"] == bundle.manifest.resources[0].svg_hash
    assert [upload["content_type"] for upload in _uploads(recorded)] == [
        "image/png",
        "image/svg+xml",
    ]


def test_a_recorded_figure_replays_with_its_caption_and_alt_text(tmp_path: Path) -> None:
    bundle = Bundle(tmp_path / "bundle")
    sink = RecordingSink(bundle, Mock(spec=BookshelfClient), ContentCache(tmp_path / "cache"))
    book = sink.draft_book("example", version="v1.0.0", license="MIT", visibility="public")
    fig = Figure()
    fig.add_subplot().plot([1.0, 2.0])
    book.write(
        "fig",
        fig,
        type="figure",
        data=pl.DataFrame({"y": [1.0, 2.0]}),
        caption="A rising line.",
        alt_text="A line chart climbing from one to two.",
    )
    book.publish()
    bundle.write()
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client:
        replay_bundle_sync(bundle, client)

    sent = {resource["name"]: resource for resource in replayed(recorded)["resources"]}
    assert sent["fig"]["discovery"] == {
        "caption": "A rising line.",
        "alt_text": "A line chart climbing from one to two.",
    }
    assert "discovery" not in sent["fig-data"]


@pytest.mark.parametrize(
    ("resource", "match"),
    [
        ("table", "resource 'table' is type 'tabular'"),
        ("fig", "public figure with no alt text"),
    ],
)
def test_a_hand_edited_bundle_the_platform_would_refuse_uploads_nothing(
    tmp_path: Path, resource: str, match: str
) -> None:
    """A draft replays without validate, so the words are checked before the first upload."""
    bundle = Bundle(tmp_path / "bundle")
    sink = RecordingSink(bundle, Mock(spec=BookshelfClient), ContentCache(tmp_path / "cache"))
    book = sink.draft_book("example", version="v1.0.0", license="MIT", visibility="public")
    book.write("table", pl.DataFrame({"y": [1.0]}), type="tabular")
    book.write("fig", Figure(), type="figure", alt_text="An empty axis.")
    bundle.write()
    edited = Bundle.read(bundle.root)
    if resource == "table":
        edited.manifest.resources[0].caption = "Not a figure."
    else:
        edited.manifest.resources[1].alt_text = None
    recorded: list[httpx.Request] = []

    with replay_client(recorded) as client, pytest.raises(InvalidBundleError, match=match):
        replay_bundle_sync(edited, client)

    assert recorded == []
