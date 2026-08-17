# %% [markdown]
# # A figure beside the frame it plots
#
# The png is drawn here rather than checked in, so it stays in step with the data.
# It is written as a `document`, which is the type for something a person reads
# rather than something a query engine scans.

# %%
import struct
import zlib

import pandas as pd

import bookshelf
from bookshelf import models

# %%
bs, book = bookshelf.setup()

# %%
raw = bs.use("raw")
emissions = pd.read_csv(raw.path)

# %% [markdown]
# ## The frame the figure plots

# %%
by_region = emissions.groupby("region", as_index=False)["value"].sum()

# %% [markdown]
# ## Drawing the png
#
# The bars are drawn into a pixel buffer with the standard library alone.
# A plotting library would be the normal choice in a real feedstock.
# The point here is the entry, not the rendering, and this keeps the bytes identical everywhere.

# %%
WIDTH, HEIGHT, MARGIN = 240, 120, 10
BACKGROUND, BAR = (255, 255, 255), (31, 119, 180)


# %%
def bar_chart(values: list[float]) -> bytes:
    """Render one bar per value as a png, tallest bar filling the plot height."""
    pixels = [[BACKGROUND] * WIDTH for _ in range(HEIGHT)]
    span = (WIDTH - 2 * MARGIN) // len(values)
    tallest = max(values)
    for index, value in enumerate(values):
        height = round((HEIGHT - 2 * MARGIN) * value / tallest)
        left = MARGIN + index * span
        for row in range(HEIGHT - MARGIN - height, HEIGHT - MARGIN):
            for column in range(left, left + span - 4):
                pixels[row][column] = BAR
    return _png(pixels)


# %%
def _png(pixels: list[list[tuple[int, int, int]]]) -> bytes:
    """Encode rows of RGB triples as a png, with no filtering and no ancillary chunks."""
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in pixels)
    header = struct.pack(">2I5B", len(pixels[0]), len(pixels), 8, 2, 0, 0, 0)
    chunks = [(b"IHDR", header), (b"IDAT", _stored_zlib(raw)), (b"IEND", b"")]
    return b"\x89PNG\r\n\x1a\n" + b"".join(
        struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
        for kind, payload in chunks
    )


# %%
def _stored_zlib(raw: bytes) -> bytes:
    """Wrap bytes in a zlib stream of uncompressed blocks.

    A compressor would shrink this, but its output varies between zlib builds,
    and a golden over the png bytes has to hold on every machine.
    """
    blocks = [raw[start : start + 0xFFFF] for start in range(0, len(raw), 0xFFFF)] or [b""]
    body = b"".join(
        bytes([index == len(blocks) - 1]) + struct.pack("<2H", len(block), len(block) ^ 0xFFFF) + block
        for index, block in enumerate(blocks)
    )
    return b"\x78\x01" + body + struct.pack(">I", zlib.adler32(raw))


# %%
figure = bar_chart(by_region["value"].tolist())

# %% [markdown]
# ## Writing both
#
# The frame carries a data dictionary describing its columns.
# The figure carries none, because a png has no columns to describe.
# `book.write` attaches each under the name it registered as.

# %%
book.write(
    "by_region",
    by_region,
    used=[raw],
    data_dictionary=[
        models.DataDictionaryEntry(name="region", description="The region the total covers."),
        models.DataDictionaryEntry(
            name="value",
            description="Summed emissions.",
            role="measure",
            unit="Mt CO2 / yr",
        ),
    ],
)
book.write("by_region_figure", figure, type="document", used=[raw])
book.publish()
