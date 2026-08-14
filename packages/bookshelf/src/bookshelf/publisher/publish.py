"""Decide what publishing a recorded bundle should do, and do it."""

from dataclasses import dataclass
from typing import Literal

from bookshelf.facade import Bookshelf
from bookshelf.publisher.bundle import Bundle
from bookshelf.publisher.replay import replay_bundle_sync

PublishKind = Literal["no-op", "would-publish", "published"]
"""What a publish did: nothing, nothing yet, or a replay through to publication."""


@dataclass(frozen=True, kw_only=True)
class PublishOutcome:
    """What publishing a bundle resolved to.

    ``converged`` says the request matched a book already published under its seal,
    so the publish was a no-op and the edition is the one that was already there.
    ``resource_count`` counts what the request carried
    and ``dedupe_hits`` how many of those resolved to content the deployment already held.
    Neither says what was written: a converged replay still recognises its resources.
    ``edition`` is ``None`` for a dry run, which resolves no edition because it sends nothing.
    """

    kind: PublishKind
    edition: int | None
    resource_count: int
    dedupe_hits: int
    converged: bool


def publish_bundle(bundle: Bundle, bs: Bookshelf, *, dry_run: bool = False) -> PublishOutcome:
    """Replay a recorded bundle to publish it, converging on one edition.

    The server settles convergence from the request alone,
    so a repeated publish is a no-op rather than a rival edition
    and a dry run is a local report rather than a probe that allocates anything.

    Args:
        bundle: Loaded bundle to publish.
        bs: Open synchronous client used for the replay.
        dry_run: Report what would be sent without sending it.

    Returns:
        What the publish resolved to.

    Raises:
        InvalidBundleError: The bundle has no book framing.
        ValueError: The bundle contains an invalid resource representation.
    """
    # Ask for the framing first, so a resources-only bundle is named as such
    # rather than replayed as a book that publishes nothing.
    bundle.require_framing()
    resources = len(bundle.manifest.resources)
    if dry_run:
        return PublishOutcome(
            kind="would-publish",
            edition=None,
            resource_count=resources,
            dedupe_hits=0,
            converged=False,
        )

    response = replay_bundle_sync(bundle, bs)
    return PublishOutcome(
        kind="no-op" if response.converged else "published",
        edition=None if response.book is None else response.book.edition,
        resource_count=response.resource_count,
        dedupe_hits=response.dedupe_hits,
        converged=response.converged,
    )


__all__ = ["PublishKind", "PublishOutcome", "publish_bundle"]
