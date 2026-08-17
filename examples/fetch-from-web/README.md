# `fetch-from-web`

One upstream url, verified against its declared digest, cached, and catalogued as a pointer.

This example needs the network, so `python examples/run_all.py` skips it
and `python examples/run_all.py --network` runs it.
The runner reads that off the recipe: a book declaring a resource with a `uri:` needs the network,
and a `path:` resource is read from beside the recipe.

The url is pinned to a commit rather than to a branch, so the bytes cannot move under it.
`sha256` is what the fetch is checked against, and a download that does not match it is a hard failure
with no retry.

## Why the golden stays stable

The golden run does not hit the network.
The declared digest is the cache key, so a hit serves the bytes locally and touches nothing remote.

That is the whole reason this example can carry a golden at all.
If the upstream file changes, the run fails on the digest check, which names the real cause.
It does not surface as a mysterious diff in `expected/manifest.lock`
that a reviewer would be tempted to refresh away.
Refreshing a golden is never the fix for an upstream content change.

```bash
bookshelf record --recipe examples/fetch-from-web/bookshelf.yaml --version v1.0.0 --bundle /tmp/ffw
bookshelf validate /tmp/ffw
```
