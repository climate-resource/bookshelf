"""Decide what publishing a recorded bundle should do, and do it."""

from dataclasses import dataclass
from typing import Literal

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
        ValueError: The bundle has no book framing or contains an invalid resource representation.
    """
    bundle_hash = compute_book_bundle_hash(bundle.manifest)
    resources = len(bundle.manifest.resources)
    drafted = draft_bundle_book_sync(bundle, bs)
    if drafted.status == "published":
        return PublishOutcome(
            kind="no-op",
            edition=drafted.metadata.edition,
            resources=0,
            bundle_hash=bundle_hash,
        )
    if dry_run:
        return PublishOutcome(
            kind="would-publish",
            edition=drafted.metadata.edition,
            resources=resources,
            bundle_hash=bundle_hash,
        )
    published = replay_bundle_sync(bundle, bs, draft=drafted)
    return PublishOutcome(
        kind="published",
        edition=published.metadata.edition,
        resources=resources,
        bundle_hash=bundle_hash,
    )


__all__ = ["PublishKind", "PublishOutcome", "publish_bundle"]
