# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Publishing a book
#
# This guide covers the publication side of the SDK.
# Publishing splits into two halves.
#
# - **Recording** runs the processing and captures what would be published into a bundle.
#   It reads from the API and writes only to the local filesystem, so it needs no credentials.
# - **Replay** takes that bundle and performs the writes.
#   This is the half that needs credentials.
#
# This guide records.
# It runs unauthenticated on every docs build,
# and the replay step is shown but not executed.
#
# The split is worth having in its own right.
# A recorded bundle can be reviewed, diffed, and archived before anything is written,
# and replaying the same bundle twice converges on one published edition.

# %%
import os
import tempfile
from pathlib import Path

os.environ.setdefault("BOOKSHELF_URL", "https://bookshelf-staging.ovh.climateresource.com.au")

from bookshelf.publisher import Bundle, RecordingBookshelf

VOLUME = "demo-sdk-howto"
VERSION = "v1.0.0"

# %% [markdown]
# ## Opening a recording
#
# A `Bundle` is a directory holding a manifest and the content addressed bytes
# of every resource the run registers.
#
# `RecordingBookshelf` is the ordinary `Bookshelf` facade with the producer seam rebound.
# Reads stay live.
# `activity()`, `draft_book()` and `register_external()` land in the bundle instead of the API.
#
# `auth=None` is passed here to prove the point.
# It keeps the client unauthenticated, so nothing in this guide can depend on a credential.

# %%
bundle_root = Path(tempfile.mkdtemp()) / "bundle"
bundle = Bundle(bundle_root)

bs = RecordingBookshelf(
    bundle,
    auth=None,
    authors=[{"name": "Climate Resource", "email": "info@climate-resource.com"}],
)

# %% [markdown]
# ## The volume has to exist
#
# A volume is the container holding every version and edition of a dataset.
# Drafting a book does not create one,
# so the first publish of a new dataset has to create it explicitly.
#
# This is a live write, so it is not part of the recorded half.
# Run it once, against the deployment, with credentials.
#
# ```python
# from bookshelf import Bookshelf
#
# with Bookshelf() as bs:
#     bs.create_volume(
#         "demo-sdk-howto",
#         license="CC-BY-4.0",
#         description="Demonstration volume for the Bookshelf SDK how-to guides.",
#     )
# ```
#
# The licence is fixed at creation and cannot be changed afterwards.
# Creating needs WRITE and deleting needs ADMIN,
# so a credential can create a volume it is not able to remove.

# %% [markdown]
# ## Deriving some data
#
# Reads are live, so take a published book as the input.
# The output then has real lineage to record.

# %%
source = bs.book("rcmip-emissions", "v5.1.0")["magicc"]

frame = source.as_df(
    region="World",
    variable="Emissions|CO2",
    year_min=2020,
    year_max=2100,
    drop_constant=True,
)
frame.shape

# %% [markdown]
# Any transformation will do.
# Here it is the scenario mean, which is a genuinely derived product.

# %%
derived = frame.groupby("scenario").mean()
derived.iloc[:5, :5]

# %% [markdown]
# ## Framing the book first
#
# Draft the book before registering anything.
# The book's visibility becomes the default for every resource recorded afterwards,
# so declaring the book public is enough to publish public data.
#
# A recorded book needs an explicit licence.

# %%
draft = bs.draft_book(
    VOLUME,
    version=VERSION,
    license="CC-BY-4.0",
    description="Scenario mean CO2 emissions derived from RCMIP.",
)
type(draft).__name__

# %% [markdown]
# The bundle is pre-edition.
# The server assigns the edition during replay,
# so the recorded framing never carries one.

# %% [markdown]
# ## Registering inside an activity
#
# Managed resources are produced only inside an activity.
# The activity derives a stable config hash,
# records runtime provenance,
# serialises the object,
# and captures explicit usage and generation lineage.
#
# `code_ref` and `config` are what make a run reproducible.
# `code_ref` defaults to a reference derived from the working tree when it is omitted.
#
# `runner` defaults to the machine's hostname.
# It is set explicitly here so the recorded manifest is identical on every build.

# %%
with bs.activity(
    code_ref="github.com/climate-resource/bookshelf@docs",
    config={"source": "rcmip-emissions/v5.1.0", "statistic": "scenario-mean"},
    runner="docs-build",
) as activity:
    output = activity.register(
        derived,
        type="timeseries",
        logical_key="demo-sdk-howto/scenario-mean",
        used=[source],
    )

output.tracking_id

# %% [markdown]
# `used=` records the inputs this output was derived from.
# A bare string or UUID is read as a tracking id,
# a handle like the `BookEntry` above supplies its own,
# and `Used(logical_key=...)` resolves by producer supplied key instead.
#
# Replay does not resolve these references again,
# so the published edition's lineage is exactly what this notebook expressed.

# %% [markdown]
# ## Attaching and marking for publication
#
# Attaching and publishing are separate editorial calls.
# Under a recording, `publish()` marks the book for publication during replay
# rather than publishing anything now.

# %%
draft.attach(output, name_in_book="scenario-mean")
draft.publish()

bundle.validate()
bundle.write()

# %% [markdown]
# ## What was recorded
#
# The bundle is a directory, and this is the whole of it.
# Resource bytes are content addressed, so identical bytes share one file.

# %%
for path in sorted(bundle_root.rglob("*")):
    size = f"{path.stat().st_size:>8} bytes" if path.is_file() else ""
    print(f"{path.relative_to(bundle_root)}  {size}")

# %% [markdown]
# The manifest is the realised provenance state.
# It carries the activity envelope, the book framing, and one record per registration.

# %%
print((bundle_root / "manifest.lock").read_text())

# %% [markdown]
# Note what is in there.
#
# - `config_hash` is derived from the `config` passed to the activity, so an identical run hashes identically.
# - `used` points at the real tracking id of the RCMIP entry this was derived from.
# - `published: true` is what `draft.publish()` set.
# - `kind: managed` means the platform re-hosts the bytes, which are the file listed above.
#
# This is reviewable before anything is written.
# That is the reason to record rather than publish directly.

# %% [markdown]
# ## Replaying
#
# Replay performs the writes, and needs credentials with `bookshelf:write`.
#
# ```bash
# bookshelf auth login
# ```
#
# ```python
# from bookshelf import Bookshelf
# from bookshelf.publisher import Bundle, replay_bundle_sync
#
# with Bookshelf() as bs:
#     book = replay_bundle_sync(Bundle.read(bundle_root), bs)
# ```
#
# Replay keys the draft on the bundle's content hash,
# attaches each entry, and publishes.
# Two replays of the same bundle converge on one published edition rather than making two,
# and a prior partial replay resumes its draft instead of stranding it.
#
# `replay_bundle` is the awaited form for async workflows.
# `publish_bundle` publishes a recorded bundle rather than replaying one,
# and returns a `PublishOutcome` saying what the publish resolved to.

# %% [markdown]
# ## Where to next
#
# - [Cataloguing external data](catalogue_external_data) covers pointers to data
#   the platform does not store, and batch registration.
