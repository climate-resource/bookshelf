# `figures`

A figure published with the values it plots.

The figure is written with `type="figure"`.
A figure's master is always a png, and the platform derives every other size from it.

`data=by_region` records the plotted values as an ordinary `tabular` entry named `by_region_figure-data`.
The figure cites it as an input, so lineage reads raw data, then plotted values, then figure.
A reviewer can download the exact numbers behind the picture.
Only the figure cites the values,
so the notebook documents recorded at the end of the build do not claim to be derived from them.

The values carry no data dictionary, because `data=` writes them without one.

A real feedstock passes a matplotlib figure, and the SDK saves it as a png at least 2400 px wide.
This example passes png bytes instead.
The bars are drawn into a pixel buffer with the standard library alone,
and the png is written with uncompressed deflate blocks.
Matplotlib's png bytes differ between platforms,
so this keeps the bytes identical on every machine, which is what lets the golden hold.

```bash
bookshelf record --recipe examples/figures/bookshelf.yaml --version v1.0.0 --bundle /tmp/figures
bookshelf validate /tmp/figures
```
