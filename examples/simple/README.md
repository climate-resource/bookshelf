# `simple`

The smallest recipe.

This recipe has not `resources:` instead a dataframe is built from literals and written with `book.write`.

Record it on its own with:

```bash
bookshelf record --recipe examples/simple/bookshelf.yaml --version v1.0.0 --bundle /tmp/simple
bookshelf validate /tmp/simple
```
