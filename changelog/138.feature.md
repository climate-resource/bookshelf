Adds `bookshelf record`, `bookshelf validate` and `bookshelf publish`,
so a feedstock and a CI action drive the publishing surface through one entry point
instead of each writing its own Python against `bookshelf.publisher`.

- `record` wraps `run_record` and refuses to replace an existing bundle unless `--force` is passed.
- `validate` is the strict check: book framing present and marked published,
  every book entry resolving to a resource,
  and every managed resource re-hashed against its manifest entry.
- `publish` drafts against the bundle hash first,
  so an already published edition reports `no-op` rather than replaying.
  `--dry-run` reports the outcome without publishing.
- A structurally invalid bundle exits 7, which is distinct from an unexpected failure.
- `record` needs the `publish` extra and says so with a usage exit code.
  `validate` and `publish` run on a core install.
