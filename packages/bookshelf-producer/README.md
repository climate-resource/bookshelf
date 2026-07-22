# Bookshelf Producer

A package for producing `Books`.

```text
    pip install bookshelf-producer
```

## This package is retiring

`bookshelf-producer` is frozen.
It will be retired once every feedstock has migrated to the support an API driven approach.
No new features will be added here.

Its `bookshelf` dependency is pinned below `0.5.0`,
because the `bookshelf` distribution will be migrated to the Bookshelf SDK at that version
and the producer write path it calls is being replaced rather than shimmed.
Nothing else changes for anyone still using it.
The `bookshelf run` and `bookshelf publish` commands keep working as they are.
