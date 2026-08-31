# `resource-attribution`

A book whose resources are not all by the same people.

The recipe format is very flexible in how authorship can be declared to handle various real-world use-cases.
The preference is to explicitly declare the authors on the resources they created.
This helps build a better citation graph.

This book credits the upstream team as authors, because the data is theirs.
Climate Resource assembled the book and appears under `volume.maintainers`, which is a contact rather than a credit.
That book-level claim still does not describe either resource inside it.
`upstream` is somebody else's workbook, published under their terms, and `totals` is derived from it here.

- A declared input states its authorshop under `resources:` in the recipe.
- A produced output defines it under `books:` and passes that information to `book.write`.

The input keeps the upstream `CC-BY-SA-4.0`, while the book and its derived output go out under `CC-BY-4.0`.

```bash
bookshelf record --recipe examples/resource-attribution/bookshelf.yaml --version v1.0.0 --bundle /tmp/ra
bookshelf validate /tmp/ra
```
