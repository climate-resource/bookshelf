# `resource-attribution`

A book whose resources are not all by the same people.

The book credits Climate Resource, because Climate Resource assembled it.
That claim does not describe either resource inside it.
`upstream` is somebody else's workbook, published under their terms, and `totals` is derived from it here.

A resource states its own catalogue metadata and inherits none of the book's,
so a field nobody wrote stays unset.
The two ends of the produce path spell the fields identically:

- A declared input states them under `resources:` in the recipe.
- A produced output passes them to `book.write`.

`license` is the case that makes the point.
The input keeps the upstream `CC-BY-SA-4.0`, while the book and its derived output go out under `CC-BY-4.0`.

```bash
bookshelf record --recipe examples/resource-attribution/bookshelf.yaml --version v1.0.0 --bundle /tmp/ra
bookshelf validate /tmp/ra
```
