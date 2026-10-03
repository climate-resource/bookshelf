# Cache

Downloads are cached by content hash under `$BOOKSHELF_CACHE_DIR`.
Pass a `ContentCache` as `cache=` to `Bookshelf` or `AsyncBookshelf` to move it for one client.

The members below are the promised surface.
`ContentCache` has other public methods, such as `fetch` and `put`,
which the SDK uses to fill the cache and which may change in any release.
The files inside the cache directory are private, so read them only through these calls.

::: bookshelf.ContentCache
    options:
      members:
        - __init__
        - get
        - summary
        - evict_lru
        - clear

::: bookshelf.CacheSummary
