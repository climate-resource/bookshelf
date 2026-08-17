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
# # Cataloguing external data and batch registration
#
# [Publishing a book](publish_a_book) recorded one derived resource
# whose bytes the platform stores.
# This guide covers the two other producer shapes:
#
# - cataloguing a pointer to data that lives somewhere else
# - registering many outputs in one request
#
# Like that guide, this one records into a bundle rather than publishing,
# so it needs no credentials.
# Replay is the half that writes.

# %%
import os
import tempfile
from pathlib import Path

os.environ.setdefault("BOOKSHELF_URL", "https://bookshelf-staging.ovh.climateresource.com.au")

import pandas as pd
import yaml

from bookshelf import RegisterItem
from bookshelf.publisher import Bundle, RecordingBookshelf

bundle_root = Path(tempfile.mkdtemp()) / "bundle"
bundle = Bundle(bundle_root)

bs = RecordingBookshelf(
    bundle,
    auth=None,
    authors=[{"name": "Climate Resource"}],
)

draft = bs.draft_book("demo-sdk-howto", version="v1.1.0", license="CC-BY-4.0")

# %% [markdown]
# ## Cataloguing an external pointer
#
# `register_external()` records a resource the platform does not hold the bytes for.
# Use it for data behind a licence, on a partner's server, or too large to copy.
#
# On the facade it catalogues the pointer without attributing it to any run.
# The same call on an activity attributes it to that run instead.

# %%
pointer = bs.register_external(
    type="tabular",
    uri="https://zenodo.org/records/4741285/files/CEDS_v2021-04-21_emissions.zip",
    name="ceds-upstream",
    metadata={"source": "Zenodo", "doi": "10.5281/zenodo.4741285"},
    tags=["external", "upstream"],
)
pointer.tracking_id

# %% [markdown]
# Passing `hash=` records the expected SHA256,
# so a later fetch can be verified against it.
# A hashless pointer receives the same synthetic hash the backend would compute.
#
# The URI must be `https`.
# Object store schemes such as `s3://` are rejected,
# so mirror to an HTTPS endpoint before cataloguing.

# %% [markdown]
# ## One activity per recorded build
#
# A recorded build supports exactly one activity block.
# Opening a second raises, because a bundle carries a single activity envelope
# and two runs would have nothing to distinguish their provenance.
# A build needing two distinct envelopes needs two bundles.
#
# So everything this run produces goes in one block,
# which here means an attributed external pointer alongside a batch of managed outputs.
#
# Called inside an activity, `register_external()` records that this run produced the pointer,
# and `used=` records what it consumed.
# `register_many()` then takes `RegisterItem` values and registers them together,
# which is the right call whenever a run produces more than one output,
# because against a live API it is a single round trip and one lineage record.

# %%
years = [str(year) for year in range(2020, 2031)]


def series(offset: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "region": "World",
                "variable": "Emissions|CO2",
                "unit": "Mt CO2/yr",
                "model": "demo",
                "scenario": f"demo-{offset:g}",
                **{year: 40.0 + offset - index for index, year in enumerate(years)},
            }
        ]
    )


with bs.activity(
    code_ref="github.com/climate-resource/bookshelf@docs",
    config={"step": "mirror-and-batch"},
    runner="docs-build",
) as activity:
    mirrored = activity.register_external(
        type="tabular",
        uri="https://example.climateresource.com.au/ceds/mirror.parquet",
        name="ceds-mirror",
        used=[pointer],
    )
    outputs = activity.register_many(
        [
            RegisterItem(
                obj=series(offset),
                type="timeseries",
                name=f"batch-{index}",
            )
            for index, offset in enumerate([0.0, 1.5, 3.0])
        ],
    )

# A name is a write-time coordinate, so the read model does not echo it back.
# The manifest below is where the recorded names are read from,
# and a resource keeps that name when it is attached to the book.
mirrored.tracking_id, [item.tracking_id for item in outputs]

# %% [markdown]
# ## What a mixed bundle looks like
#
# Every registration above is now in one manifest,
# with `kind` distinguishing the two sorts.
# A pointer carries `external_uri` and has no byte file.
# A managed record carries `size` and its bytes sit under `resources/`.

# %%
draft.attach(outputs[0], name_in_book="batch-0")
draft.publish()
bundle.validate()
bundle.write()

for path in sorted(bundle_root.rglob("*")):
    size = f"{path.stat().st_size:>8} bytes" if path.is_file() else ""
    print(f"{path.relative_to(bundle_root)}  {size}")

# %%
manifest = yaml.safe_load((bundle_root / "manifest.lock").read_text())

for record in manifest["resources"]:
    print(f"{record['kind']:<8} {record['name']:<34} {record.get('external_uri', '')}")

# %% [markdown]
# ## Batch limits and partial failure
#
# These rules apply when the batch reaches the API,
# so on replay or through a live facade.
#
# - An atomic batch over 1000 items raises before any upload begins.
# - A larger non atomic batch is split into requests of at most 1000 items.
# - `atomic=True` is the default, so the whole batch succeeds or none of it does.
#
# With `atomic=False` the facade finishes every chunk even when items fail,
# then raises `PartialRegistrationError`.
# The error is the useful part, because it carries what did land.
#
# ```python
# try:
#     outputs = activity.register_many(items, atomic=False)
# except PartialRegistrationError as exc:
#     # Committed resources, usable straight away.
#     for resource in exc.successful_resources:
#         ...
#     # Each failure, with the typed error the server gave.
#     for failure in exc.failures:
#         print(failure.index, failure.error)
# ```
#
# Index `-1` in `failed_indices` is not an item.
# It identifies a batch level lineage failure reported by the server.

# %% [markdown]
# ## Deduplication
#
# `dedupe` defaults to true and is recorded per resource,
# because the server resolves it rather than the recorder.

# %%
{record["name"]: record["dedupe"] for record in manifest["resources"]}

# %% [markdown]
# On replay, byte identical items owned by one organisation
# collapse to the first canonical resource,
# even when a later item supplies a different name.
# The first resource's name stays canonical.
#
# Through a live facade the handle reports this on `registration_status`.
#
# ```python
# with Bookshelf() as bs:
#     with bs.activity(code_ref="...") as activity:
#         first = activity.register(frame, type="timeseries", name="a")
#         second = activity.register(frame, type="timeseries", name="b")
#
# first.registration_status               # created
# second.registration_status              # aliased
# first.tracking_id == second.tracking_id  # True
# ```
#
# Pass `dedupe=False` when each run has to produce a distinct resource,
# for instance when re-publishing unchanged data as a new edition.

# %% [markdown]
# ## Resuming after a failed upload
#
# A failed multipart PUT can leave an unfinished upload,
# because the server has no abort endpoint.
# Registration does not begin after that failure,
# so nothing half registered is left behind.
#
# Retrying reuses the content addressed upload path and resumes safely.
# The correct response to an upload failure is to run the same code again.
