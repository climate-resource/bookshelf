# bookshelf._core

| Sub-package                                | Description                                                                            |
| ------------------------------------------ | -------------------------------------------------------------------------------------- |
| [auth][bookshelf._core.auth]               | Credential providers for the Bookshelf SDK.                                            |
| [client][bookshelf._core.client]           | Unified client for the Bookshelf SDK.                                                  |
| [config][bookshelf._core.config]           | Auth and base-URL resolution for the unified client.                                   |
| [credentials][bookshelf._core.credentials] | Stored credentials for ``bookshelf auth login``, shared with the CLI.                  |
| [errors][bookshelf._core.errors]           | Typed exception hierarchy mapped from RFC 7807 ``problem+json`` responses.             |
| [frames][bookshelf._core.frames]           | Bytes-to-DataFrame conversion for ``/data`` payloads.                                  |
| [hashing][bookshelf._core.hashing]         | Shared content-hash helpers producing the canonical ``sha256:<hex>`` format.           |
| [names][bookshelf._core.names]             | The rules for reading the two labels a book is addressed by: its name and its version. |
| [oauth][bookshelf._core.oauth]             | WorkOS OAuth flows for interactive login.                                              |
| [ops][bookshelf._core.ops]                 | I/O-free ``build_*``/``parse_*`` pairs for every operation the SDK uses.               |
| [retry][bookshelf._core.retry]             | Transient retry policy: in-process backoff on 5xx and network failures only.           |
| [types][bookshelf._core.types]             | Request/response value types for the transport core.                                   |

::: bookshelf._core