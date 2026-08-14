"""Replaying a recorded bundle through the one-call replay endpoint.

The request is the whole contract now:
names address the resources, order carries the lineage,
and the server settles convergence from what it receives.
"""

from pathlib import Path

import httpx
import pytest

from bookshelf._core.hashing import sha256_hex
from bookshelf.facade import AsyncBookshelf
from bookshelf.publisher.bundle import Bundle, BundleActivity, BundleBook
from bookshelf.publisher.replay import replay_bundle, replay_bundle_sync
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
    assert pointer["storage_path"] is None
    assert pointer["size_bytes"] is None
    assert managed["kind"] == "managed"
    assert managed["storage_path"] == "ingest/org_1/abc"
    assert managed["size_bytes"] == len(b"derived payload")


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
