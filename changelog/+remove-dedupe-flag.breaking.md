Removes the `dedupe` argument from `RegisterItem` and from every call that registers or records a resource.
The server decides: a registration aliases onto a resource your organisation already holds with the same bytes,
unless it pins its own tracking id.
A pinned `tracking_id` no longer needs `dedupe=False`.

- Registration and replay requests no longer send `dedupe`.
- The bundle manifest moves to schema 3.10 and no longer records `dedupe`.
  An older manifest that records it still loads, and the field is dropped.
- `bookshelf upload` no longer prints a `Dedupe` line.
