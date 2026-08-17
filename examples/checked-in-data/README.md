# `checked-in-data`

A resource addressed by `path:` rather than by `uri:`.

The recipe states no `sha256`, because the recorder computes the digest when it reads the file.
A `uri:` resource is the other way round: it declares the digest and the fetch is checked against it.
The two are mutually exclusive.

`path:` is relative to the recipe and the file stays beside it, so the example is self-contained and
needs no network.

The build derives one frame from the input and writes it with `used=[raw]`, which is what records
the lineage edge.

```bash
bookshelf record --recipe examples/checked-in-data/bookshelf.yaml --version v1.0.0 --bundle /tmp/cid
bookshelf validate /tmp/cid
```
