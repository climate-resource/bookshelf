# How-to guides

This part of the project documentation focuses on a **problem-oriented** approach.
We'll go over how to solve common tasks.

## Reading data

Reading public, published data needs no credentials.

* ["Reading a published book"](read_a_book):
  addressing a book, pinning an edition, exploring an entry, and trimming a query on the server.
* ["Converting and plotting"](convert_and_plot):
  the pandas, Polars, PyArrow and `ScmRun` converters,
  the verified content cache, and getting a chart on screen.
* ["Reading asynchronously"](read_asynchronously):
  the awaited facade, fetching concurrently, and how long to keep a client alive.

## Producing data

Producing data needs credentials with `bookshelf:write`.
Run `bookshelf auth login` first to login.

* ["Publishing a book"](publish_a_book):
  creating a volume, registering a derived resource with its lineage,
  then drafting, attaching and publishing.
* ["Cataloguing external data"](catalogue_external_data):
  pointers to data the platform does not store,
  batch registration, partial failure, and deduplication.
