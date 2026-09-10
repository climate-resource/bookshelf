"""Tests for storing a pull request's candidate books as one preview."""

import pytest

from bookshelf._core import errors
from bookshelf._core.client import BookshelfClient
from bookshelf.publisher.bundle import BundleBook, InvalidBundleError
from bookshelf.publisher.preview import PreviewIdentity, upload_preview
from tests._preview import BASE_URL, PREVIEW_ID, SHA, PreviewDeployment
from tests.conftest import BundleFactory

IDENTITY = PreviewIdentity(
    repository="climate-resource/feedstock",
    pr_number=7,
    pr_url="https://github.com/climate-resource/feedstock/pull/7",
    head_sha=SHA,
    main_sha=SHA,
    candidate_tree=SHA,
    run_id="42",
)


def _client(deployment: PreviewDeployment) -> BookshelfClient:
    return BookshelfClient(BASE_URL, auth=None, transport=deployment.transport())


def _framing(version: str) -> BundleBook:
    return BundleBook(volume="example", version=version, visibility="public", license="MIT")


def test_two_bundles_are_uploaded_attached_and_sealed(make_bundle: BundleFactory) -> None:
    first = make_bundle(book=_framing("v1.0.0"), entries=2)
    second = make_bundle(book=_framing("v2.0.0"))
    deployment = PreviewDeployment()

    with _client(deployment) as client:
        outcome = upload_preview([first.root, second.root], client, IDENTITY)

    assert outcome.refused == {}
    assert outcome.preview.state.value == "sealed"
    assert [target.uploaded for target in outcome.preview.targets] == [True, True]
    (created,) = deployment.sent("/previews")
    assert created["targets"] == [
        {"volume": "example", "version": "v1.0.0"},
        {"volume": "example", "version": "v2.0.0"},
    ]
    assert created["candidate"] == {"head_sha": SHA, "main_sha": SHA, "candidate_tree": SHA}
    assert deployment.requests[0].url.raw_path == (
        b"/v1/proposals/climate-resource%2Ffeedstock/7/previews"
    )
    attached = deployment.sent("/v1.0.0")
    assert [item["name"] for item in attached[0]["resources"]] == ["entry-0", "entry-1"]
    assert all(
        item["storage_path"].startswith(f"preview/org_1/{PREVIEW_ID}/sha256/")
        for item in attached[0]["resources"]
    )
    assert attached[0]["manifest"]["discovery"]["license"] == "MIT"
    assert [entry["name"] for entry in attached[0]["manifest"]["entries"]] == [
        "entry-0",
        "entry-1",
    ]
    paths = [
        request.url.path for request in deployment.requests if request.url.host != "s3.example"
    ]
    assert paths.index(f"/v1/previews/{PREVIEW_ID}/uploads") < paths.index(
        f"/v1/previews/{PREVIEW_ID}/books/example/v1.0.0"
    )
    assert paths[-1] == f"/v1/previews/{PREVIEW_ID}/seal"
    assert deployment.sent("/fail") == []


def test_an_invalid_bundle_is_still_a_target_and_fails_the_preview(
    make_bundle: BundleFactory,
) -> None:
    valid = make_bundle(book=_framing("v1.0.0"))
    unpublished = make_bundle(book=_framing("v2.0.0"), published=False)
    deployment = PreviewDeployment()

    with _client(deployment) as client:
        outcome = upload_preview([valid.root, unpublished.root], client, IDENTITY)

    assert outcome.preview.state.value == "failed"
    assert list(outcome.refused) == [unpublished.root]
    (created,) = deployment.sent("/previews")
    assert {"volume": "example", "version": "v2.0.0"} in created["targets"]
    assert deployment.sent("/v2.0.0") == []
    assert len(deployment.sent("/v1.0.0")) == 1
    (failed,) = deployment.sent("/fail")
    assert "does not record a publish operation" in failed["reason"]
    assert deployment.sent("/seal") == []


def test_an_upload_error_fails_the_preview_and_propagates(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    deployment = PreviewDeployment(refuse={"/uploads": 413})

    with _client(deployment) as client, pytest.raises(errors.APIError):
        upload_preview([bundle.root], client, IDENTITY)

    (failed,) = deployment.sent("/fail")
    assert "refused /uploads" in failed["reason"]
    assert deployment.sent("/seal") == []


def test_a_seal_error_fails_the_preview(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    deployment = PreviewDeployment(refuse={"/seal": 409})

    with _client(deployment) as client, pytest.raises(errors.ConflictError):
        upload_preview([bundle.root], client, IDENTITY)

    assert len(deployment.sent("/fail")) == 1


def test_a_multipart_upload_completes_under_the_preview(make_bundle: BundleFactory) -> None:
    bundle = make_bundle()
    deployment = PreviewDeployment(multipart=True)

    with _client(deployment) as client:
        upload_preview([bundle.root], client, IDENTITY)

    (completed,) = deployment.sent("/uploads/complete")
    assert completed["storage_path"].startswith(f"preview/org_1/{PREVIEW_ID}/")
    assert [part["part_number"] for part in completed["parts"]] == [1, 2]


def test_a_single_part_upload_is_completed_so_its_digest_is_rechecked(
    make_bundle: BundleFactory,
) -> None:
    bundle = make_bundle()
    deployment = PreviewDeployment()

    with _client(deployment) as client:
        upload_preview([bundle.root], client, IDENTITY)

    (completed,) = deployment.sent("/uploads/complete")
    assert completed["upload_id"] == "single"
    assert completed["parts"] == []
    paths = [
        request.url.path for request in deployment.requests if request.url.host != "s3.example"
    ]
    assert paths.index(f"/v1/previews/{PREVIEW_ID}/uploads/complete") < paths.index(
        f"/v1/previews/{PREVIEW_ID}/books/example/v1.0.0"
    )


def test_a_bundle_without_a_book_is_refused_before_anything_is_created(
    make_bundle: BundleFactory,
) -> None:
    bundle = make_bundle()
    bundle.manifest.book = None
    bundle.write()
    deployment = PreviewDeployment()

    with _client(deployment) as client, pytest.raises(InvalidBundleError):
        upload_preview([bundle.root], client, IDENTITY)

    assert deployment.requests == []


def test_two_bundles_building_the_same_book_are_refused(make_bundle: BundleFactory) -> None:
    first = make_bundle()
    second = make_bundle()
    deployment = PreviewDeployment()

    with _client(deployment) as client, pytest.raises(InvalidBundleError, match="both build"):
        upload_preview([first.root, second.root], client, IDENTITY)

    assert deployment.requests == []
