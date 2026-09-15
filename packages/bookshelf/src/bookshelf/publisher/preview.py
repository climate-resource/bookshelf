"""Store a pull request's candidate books as one preview on the platform.

The feedstock CI run creates the preview, uploads every book it built, then seals it.
The platform owns the check run and the pull request comment from there.
Once the preview exists, every failure is reported to it with ``fail``,
so the check run never waits for the platform's timeout.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf._produce.serialise import content_type_for
from bookshelf._produce.uploads import upload_bytes
from bookshelf.publisher.bundle import Bundle, BundleBook, InvalidBundleError
from bookshelf.publisher.replay import _activity, _book, _resource

# PreviewFailRequest.reason caps at this length.
_REASON_LIMIT = 500


@dataclass(frozen=True, slots=True)
class PreviewIdentity:
    """The pull request and the run a preview belongs to."""

    repository: str
    pr_number: int
    pr_url: str
    head_sha: str
    main_sha: str
    candidate_tree: str
    run_id: str


@dataclass(frozen=True, slots=True)
class PreviewOutcome:
    """The preview as the platform left it, with the bundles that were refused.

    ``refused`` maps a bundle path to why it was not attached.
    It is empty exactly when the preview was sealed.
    """

    preview: models.PreviewDetail
    refused: dict[Path, str]


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: Path
    bundle: Bundle
    framing: BundleBook
    problem: str | None


def _candidate(path: Path) -> _Candidate:
    """Read one bundle far enough to name its target, keeping any contract failure as its problem."""
    try:
        bundle = Bundle.read(path)
        framing = bundle.require_framing()
    except (OSError, ValueError, InvalidBundleError) as exc:
        raise InvalidBundleError(f"{path}: {exc}") from exc
    try:
        bundle.validate()
        pointers = [
            resource.name
            for resource in bundle.manifest.resources
            if resource.kind != "managed"
            and any(entry.name == resource.name for entry in framing.entries)
        ]
        if pointers:
            raise InvalidBundleError(
                f"book entries {pointers} are pointers, which a preview cannot carry"
            )
    except InvalidBundleError as exc:
        return _Candidate(path, bundle, framing, str(exc))
    return _Candidate(path, bundle, framing, None)


def _read_all(paths: Sequence[Path]) -> list[_Candidate]:
    candidates = [_candidate(path) for path in paths]
    seen: dict[tuple[str, str], Path] = {}
    for candidate in candidates:
        target = (candidate.framing.volume, candidate.framing.version)
        if target in seen:
            raise InvalidBundleError(
                f"{candidate.path} and {seen[target]} both build {target[0]} {target[1]}"
            )
        seen[target] = candidate.path
    return candidates


def _manifest(candidate: _Candidate, storage_paths: Mapping[str, str]) -> dict[str, Any]:
    """The book's manifest sections in the API's spelling, as publication reads them.

    ``activity`` and ``resources`` are the replay projections,
    so a book published from a preview keeps the provenance a replay would give it.
    ``storage_paths`` maps a resource name to where its bytes sit under the preview.
    """
    framing = candidate.framing
    manifest: dict[str, Any] = _book(framing).model_dump(mode="json", exclude_unset=True)
    if framing.processing is not None:
        manifest["processing"] = [list(pair) for pair in framing.processing]
    recorded = candidate.bundle.manifest
    if recorded.activity is not None:
        manifest["activity"] = _activity(recorded.activity).model_dump(
            mode="json", exclude_unset=True
        )
    manifest["resources"] = [
        _resource(resource, storage_paths.get(resource.name)).model_dump(
            mode="json", exclude_unset=True
        )
        for resource in recorded.resources
    ]
    return manifest


def _attach(client: BookshelfClient, preview_id: UUID, candidate: _Candidate) -> None:
    """Upload every managed resource's bytes under the preview, then attach the manifest and files.

    Inputs that are not book entries travel too,
    because the platform needs a file for every managed resource the manifest names.
    """
    by_hash: dict[str, str] = {}
    by_name: dict[str, str] = {}
    files: list[models.PreviewResourceUpload] = []
    for resource in candidate.bundle.manifest.resources:
        if resource.kind != "managed":
            continue
        if resource.hash not in by_hash:
            by_hash[resource.hash] = upload_bytes(
                client,
                candidate.bundle.resource_bytes(resource),
                hash_=resource.hash,
                content_type=content_type_for(resource.type),
                preview_id=preview_id,
            )
        by_name[resource.name] = by_hash[resource.hash]
        files.append(
            models.PreviewResourceUpload(
                name=resource.name,
                hash=resource.hash,
                type=models.ResourceType(resource.type),
                format=resource.format,
                size_bytes=resource.size,
                storage_path=by_hash[resource.hash],
            )
        )
    client.attach_preview_book(
        preview_id,
        candidate.framing.volume,
        candidate.framing.version,
        models.PreviewBookUpload(manifest=_manifest(candidate, by_name), resources=files),
    )


def _reason(text: str) -> str:
    return text if len(text) <= _REASON_LIMIT else text[: _REASON_LIMIT - 3] + "..."


def upload_preview(
    bundles: Sequence[Path],
    client: BookshelfClient,
    identity: PreviewIdentity,
) -> PreviewOutcome:
    """Create a preview for every bundle's book, attach the valid ones, then seal it.

    A bundle whose manifest names no target raises :class:`InvalidBundleError` before anything is created.
    A bundle that fails the rest of the contract is still a target,
    so the preview is failed with the reason and the outcome lists it.
    An error once the preview exists fails it with the error text, then propagates.
    """
    candidates = _read_all(bundles)
    preview = client.create_preview(
        identity.repository,
        identity.pr_number,
        models.PreviewCreate(
            candidate=models.PreviewCandidate(
                head_sha=identity.head_sha,
                main_sha=identity.main_sha,
                candidate_tree=identity.candidate_tree,
            ),
            run_id=identity.run_id,
            pr_url=identity.pr_url,
            targets=[
                models.PreviewTarget(volume=c.framing.volume, version=c.framing.version)
                for c in candidates
            ],
        ),
    )
    refused = {c.path: c.problem for c in candidates if c.problem is not None}
    try:
        for candidate in candidates:
            if candidate.problem is None:
                _attach(client, preview.id, candidate)
        if not refused:
            return PreviewOutcome(preview=client.seal_preview(preview.id), refused=refused)
    except Exception as exc:
        try:
            client.fail_preview(
                preview.id,
                models.PreviewFailRequest(reason=_reason(str(exc) or type(exc).__name__)),
            )
        except Exception as fail_exc:
            exc.add_note(f"failing the preview also failed: {fail_exc}")
        raise
    reason = "\n".join(f"{path}: {problem}" for path, problem in refused.items())
    failed = client.fail_preview(preview.id, models.PreviewFailRequest(reason=_reason(reason)))
    return PreviewOutcome(preview=failed, refused=refused)


__all__ = ["PreviewIdentity", "PreviewOutcome", "upload_preview"]
