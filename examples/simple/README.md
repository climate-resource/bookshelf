# `simple`

The smallest legal recipe.
It proves that `resources:` may be left out entirely, because a build that constructs its data
inline reads nothing.

One frame is built from literals and written with `book.write`, which registers the resource and
attaches it to the book under the same name.

Record it on its own with:

```bash
bookshelf record --recipe examples/simple/bookshelf.yaml --version v1.0.0 --bundle /tmp/simple
bookshelf validate /tmp/simple
```
