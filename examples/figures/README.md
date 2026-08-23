# `figures`

A png published beside the frame it plots.

The figure is a `document`, which is the type for something a person reads
rather than something a query engine scans.
It is drawn in the build file rather than checked in, so it cannot fall out of step with the data.

The two entries differ in one visible way.
`by_region` carries a data dictionary describing its columns.
`by_region_figure` carries none, because a png has no columns to describe,
and `expected/v1.0.0/manifest.lock` shows the entry with no `data_dictionary` key at all.

The bars are drawn into a pixel buffer with the standard library alone,
and the png is written with uncompressed deflate blocks.
A real feedstock would reach for a plotting library.
This keeps the example free of a plotting dependency and keeps the bytes identical on every machine,
which is what lets the golden hold.

```bash
bookshelf record --recipe examples/figures/bookshelf.yaml --version v1.0.0 --bundle /tmp/figures
bookshelf validate /tmp/figures
```
