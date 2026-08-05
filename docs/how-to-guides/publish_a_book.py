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
# This guide covers the producer side of the SDK:
# deriving data from something already published, registering it with its lineage,
# and assembling it into a book.
#
# Publishing needs credentials.
# Log in first, or set `$BOOKSHELF_TOKEN`.
#
# ```bash
# bookshelf auth login
# bookshelf auth whoami
# ```
#
# Creating a volume needs the `bookshelf:volumes:create` permission,
# and registering resources needs `bookshelf:write`.

# %%
import os

os.environ.setdefault("BOOKSHELF_URL", "https://bookshelf-staging.ovh.climateresource.com.au")


from bookshelf import Bookshelf, BookshelfError
from bookshelf._core.errors import ConflictError

bs = Bookshelf()

VOLUME = "demo-sdk-howto"
VERSION = "v1.0.0"

# %% [markdown]
# ## Creating the volume
#
# A volume is the container that holds every version and edition of a dataset.
# Drafting a book does not create one, so the first publish has to create it explicitly.
#
# The licence is fixed at creation and cannot be changed afterwards.
# Creating needs WRITE and deleting needs ADMIN,
# so a credential can create a volume it is not able to remove.

# %%
try:
    volume = bs.create_volume(
        VOLUME,
        license="CC-BY-4.0",
        description="Demonstration volume for the Bookshelf SDK how-to guides.",
        maintainers=[{"name": "Climate Resource", "email": "info@climate-resource.com"}],
    )
    print(f"created volume {volume.name}")
except ConflictError:
    print(f"volume {VOLUME} already exists, reusing it")

# %% [markdown]
# This guide re-runs on every docs build,
# so it tolerates the volume already being there.
# A one-off publishing script does not need the `try` block.

# %% [markdown]
# ## Deriving some data
#
# Take a published book as the input,
# so the output has real lineage to record.

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
# Here it is the scenario spread, which is a genuinely derived product.

# %%
derived = frame.groupby("scenario").mean()
derived.iloc[:5, :5]

# %% [markdown]
# ## Registering inside an activity
#
# Managed resources are produced only inside an activity.
# The activity derives a stable config hash,
# records runtime provenance,
# materialises the object,
# and sends explicit usage and generation lineage to the API.
#
# `code_ref` and `config` are what make a run reproducible.
# `code_ref` defaults to a reference derived from the working tree when it is omitted.

# %%
with bs.activity(
    code_ref="github.com/climate-resource/bookshelf@docs",
    config={"source": "rcmip-emissions/v5.1.0", "statistic": "scenario-mean"},
) as activity:
    output = activity.register(
        derived,
        type="timeseries",
        logical_key="demo-sdk-howto/scenario-mean",
        used=[source],
        dedupe=False,
    )

output.tracking_id, output.registration_status

# %% [markdown]
# `used=` records the inputs this output was derived from.
# A bare string or UUID is read as a tracking id,
# a handle like the `BookEntry` above supplies its own,
# and `Used(logical_key=...)` resolves by producer supplied key instead.
#
# `registration_status` reports how the registration resolved.
# `created` means new bytes were stored.

# %% [markdown]
# !!! note "Deduplication and re-runs"
#
#     `dedupe` defaults to true,
#     so byte identical objects owned by one organisation collapse to a single canonical resource
#     and the status comes back as `aliased`.
#     That is usually what you want.
#
#     It does not suit a guide that re-runs unchanged on every docs build,
#     because the aliased resource is already attached to a published book
#     and a resource cannot be re-pointed once that is true.
#     `dedupe=False` keeps each build independent.

# %% [markdown]
# ## Drafting and publishing
#
# Drafting, attaching, and publishing are separate editorial calls.
# Nothing is visible to consumers until `publish()` succeeds.

# %%
draft = bs.draft_book(
    VOLUME,
    version=VERSION,
    license="CC-BY-4.0",
    description="Scenario mean CO2 emissions derived from RCMIP.",
)
draft.book_id, draft.status

# %% [markdown]
# Attach each resource under the name consumers will index the book by.

# %%
try:
    draft.attach(output, name_in_book="scenario-mean")
    draft.publish()
except Exception:
    # A draft that is never published still consumes an edition number,
    # so clean it up rather than leaving an empty edition behind.
    bs.discard_draft(str(draft.book_id))
    raise

draft.status

# %% [markdown]
# The edition was allocated by the server.
# Re-running this guide publishes a new edition of the same version,
# which is exactly what an edition is for:
# the data version is unchanged and the processing was run again.

# %%
published = bs.book(VOLUME, VERSION)
published.metadata.version, published.metadata.edition

# %% [markdown]
# ## Reading it back
#
# The book is now an ordinary published book.

# %%
published["scenario-mean"].as_df(year_min=2020, year_max=2030)

# %% [markdown]
# ## Fixing a draft before it goes out
#
# `update_draft()` patches a draft's metadata,
# and `discard_draft()` deletes it.
# Both work on drafts only.
# A published book is immutable and the API rejects the attempt.

# %%
try:
    bs.discard_draft(str(published.metadata.id))
except BookshelfError as exc:
    print(f"{type(exc).__name__}: {exc}")

# %% [markdown]
# ## Where to next
#
# - [Cataloguing external data](catalogue_external_data) covers pointers to data
#   the platform does not store, and batch registration.
