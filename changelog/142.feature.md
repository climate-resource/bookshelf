Adds the volume lifecycle and draft cleanup to the SDK and the CLI,
so a new feedstock can create the collection it publishes into
and clear up after a publish that failed.

- `Bookshelf.create_volume`, `update_volume` and `delete_volume`, with `bookshelf volume create`,
  `bookshelf volume update` and `bookshelf volume delete`.
  Creation needs `WRITE` and deletion needs `ADMIN`,
  so a caller can create a volume it cannot delete.
- `Bookshelf.discard_draft` and `update_draft`, with `bookshelf discard volume@version_eNNN`.
  Only a draft can be discarded, and the CLI refuses a published edition before it asks the API.
- The asynchronous facade carries the same methods.
