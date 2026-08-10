"""Decide what publishing a recorded bundle should do, and do it."""

from dataclasses import dataclass
from typing import Literal

from bookshelf._produce.books import DraftBook
from bookshelf.facade import Bookshelf
from bookshelf.publisher.bundle import Bundle, compute_book_bundle_hash
from bookshelf.publisher.replay import draft_bundle_book_sync, replay_bundle_sync

PublishKind = Literal["no-op", "would-publish", "published"]
"""What a publish did: nothing, nothing yet, or a replay through to publication."""


@dataclass(frozen=True, kw_only=True)
class PublishOutcome:
    """What publishing a bundle resolved to.

    ``resources`` counts what the publish replayed,
    so it is zero for an edition that already exists.
    ``bundle_hash`` is the key the edition converges on.
    """

    kind: PublishKind
    edition: int
    resources: int
    bundle_hash: str


def publish_bundle(bundle: Bundle, bs: Bookshelf, *, dry_run: bool = False) -> PublishOutcome:
    """Replay a recorded bundle to publish it, converging on one edition.

    Drafting is the only way to learn whether the edition already exists,
    and the draft is keyed on the bundle hash,
    so a dry run adds no edition of its own.
    The draft this decision rests on is the one the replay resumes.

    Args:
        bundle: Loaded bundle to publish.
        bs: Open synchronous client used for the draft and the replay.
        dry_run: Resolve the edition and report the outcome without replaying.

    Returns:
        What the publish resolved to.

    Raises:
        InvalidBundleError: The bundle has no book framing.
        ValueError: The bundle contains an invalid resource representation.
    """
    # Ask for the framing before hashing it,
    # so a resources-only bundle is named as such
    # rather than reported as a seal that cannot be computed.
    bundle.require_framing()
    bundle_hash = compute_book_bundle_hash(bundle.manifest)
    resources = len(bundle.manifest.resources)
    drafted = draft_bundle_book_sync(bundle, bs)

    def outcome(kind: PublishKind, book: DraftBook, counted: int) -> PublishOutcome:
        return PublishOutcome(
            kind=kind,
            edition=book.metadata.edition,
            resources=counted,
            bundle_hash=bundle_hash,
        )

    if drafted.status == "published":
        return outcome("no-op", drafted, 0)
    if dry_run:
        return outcome("would-publish", drafted, resources)
    return outcome("published", replay_bundle_sync(bundle, bs, draft=drafted), resources)


__all__ = ["PublishKind", "PublishOutcome", "publish_bundle"]
