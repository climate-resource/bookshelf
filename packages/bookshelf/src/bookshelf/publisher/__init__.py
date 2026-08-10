"""Public record, replay and publish surface.

Use :func:`replay_bundle` with a bundle directory when replay is part of an async Python workflow::

    from pathlib import Path

    from bookshelf import AsyncBookshelf
    from bookshelf.publisher import replay_bundle

    async with AsyncBookshelf() as bs:
        book = await replay_bundle(Path("bundle"), bs)

Load :class:`Bundle` first
when the caller needs to inspect or validate the manifest before allowing writes::

    from pathlib import Path

    from bookshelf import AsyncBookshelf
    from bookshelf.publisher import Bundle, replay_bundle

    bundle = Bundle.read(Path("bundle"))
    bundle.require_framing()

    async with AsyncBookshelf() as bs:
        book = await replay_bundle(bundle, bs)

Both Python forms use the same replay implementation.
A path is loaded into a ``Bundle`` before replay.
Replaying the same content converges on the same published edition.
A prior partial replay resumes its draft,
while a bundle whose recorded book was not marked for publication remains a draft.

Synchronous applications use :func:`replay_bundle_sync` with :class:`bookshelf.Bookshelf`::

    from pathlib import Path

    from bookshelf import Bookshelf
    from bookshelf.publisher import replay_bundle_sync

    with Bookshelf() as bs:
        book = replay_bundle_sync(Path("bundle"), bs)

Use :func:`publish_bundle` to publish a recorded bundle rather than to replay one.
It returns a :class:`PublishOutcome` saying what the publish resolved to::

    with Bookshelf() as bs:
        outcome = publish_bundle(Bundle.read(Path("bundle")), bs)
"""

from bookshelf.publisher.bundle import (
    Bundle,
    BundleManifest,
    compute_book_bundle_hash,
)
from bookshelf.publisher.publish import PublishOutcome, publish_bundle
from bookshelf.publisher.recipe import RecordRecipe, load_record_recipe
from bookshelf.publisher.record import (
    Build,
    parse_parameters,
    run_record,
    setup,
)
from bookshelf.publisher.recording import (
    RecordedDraftBook,
    RecordedResource,
    RecordingActivity,
    RecordingBookshelf,
    RecordingSink,
)
from bookshelf.publisher.reference import BookshelfReference
from bookshelf.publisher.replay import replay_bundle, replay_bundle_sync
from bookshelf.publisher.resource import ResolvedResource, resolve_resource

__all__ = [
    "BookshelfReference",
    "Bundle",
    "BundleManifest",
    "PublishOutcome",
    "RecordRecipe",
    "RecordedDraftBook",
    "RecordedResource",
    "RecordingActivity",
    "RecordingBookshelf",
    "RecordingSink",
    "Build",
    "ResolvedResource",
    "compute_book_bundle_hash",
    "load_record_recipe",
    "parse_parameters",
    "publish_bundle",
    "replay_bundle",
    "replay_bundle_sync",
    "resolve_resource",
    "run_record",
    "setup",
]
