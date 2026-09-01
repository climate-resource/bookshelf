# How-to guides

This part of the project documentation focuses on a **problem-oriented** approach.
We'll go over how to solve common tasks.

## Reading data

Reading public, published data needs no credentials.

- [Finding volumes and books](find_volumes_and_books) searches the catalogue,
  filters it, and lists every book in a volume.
- [Reading a published book](read_a_book) addresses a book, pins an edition,
  explores an entry before downloading it, and trims a query on the server.
- [Converting and plotting](convert_and_plot) covers the pandas, Polars, PyArrow and `ScmRun`
  converters, the verified content cache, and getting a chart on screen.
- [Reading asynchronously](read_asynchronously) covers the awaited facade, fetching several books
  at once, and how long a client should live.

## Producing data

Producing splits into two halves.
Recording captures what would be published into a local bundle, so it needs no credentials.
Replay performs the writes and needs `bookshelf:write`, so run `bookshelf auth login` first.

Both guides record, and both show the replay step without running it.

- [Publishing a book](publish_a_book) frames a book, registers a derived resource with its lineage,
  and reads the recorded manifest back before anything is written.
- [Cataloguing external data](catalogue_external_data) covers pointers to data the platform does not
  store, batch registration, partial failure, and deduplication.

## Maintaining a feedstock

- [Keeping pinned books up to date with Renovate](renovate_updates.md) wires Renovate to the
  platform's release feed, so a stale `bookshelf://` pin becomes an ordinary dependency-update
  pull request.
