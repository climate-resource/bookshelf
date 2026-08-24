# bookshelf._produce

| Sub-package                                 | Description                                                                          |
| ------------------------------------------- | ------------------------------------------------------------------------------------ |
| [activities][bookshelf._produce.activities] | Activity contexts for registering produced resources.                                |
| [books][bookshelf._produce.books]           | Mutable draft-book handles for producer workflows.                                   |
| [facade][bookshelf._produce.facade]         | Producer write adapters and the seam the public facades bind to.                     |
| [helpers][bookshelf._produce.helpers]       | Shared helpers for synchronous and asynchronous production.                          |
| [provenance][bookshelf._produce.provenance] | Git provenance and config-hash helpers for the activity surface.                     |
| [resources][bookshelf._produce.resources]   | Resource handles enriched with producer registration outcomes.                       |
| [serialise][bookshelf._produce.serialise]   | Materialise an in-memory object into the bytes a registration uploads.               |
| [types][bookshelf._produce.types]           | Public value types for producing Bookshelf resources.                                |
| [uploads][bookshelf._produce.uploads]       | Put already-serialised bytes into managed storage, returning the key they landed at. |
| [visibility][bookshelf._produce.visibility] | The visibility argument shared by every producer registration surface.               |

::: bookshelf._produce