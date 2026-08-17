# `complex-processing`

Several outputs, and a lineage graph that follows the processing rather than the inputs.

`book.write` returns the resource it registered.
Passing that handle to a later `used=` is what records the edge from the earlier output to the later one.
The build reads one checked-in input and writes four resources:

- `cleaned` is derived from `raw`.
- `by_region` and `world` are each derived from `cleaned`.
- `shares` is derived from `by_region` and `world`.

A recorded bundle carries one activity, so the `used` list on a resource is
everything that activity had consumed by the time the resource was registered,
not the arguments of that one `write` call.
`cleaned` therefore lists `raw` alone and `shares` lists all four,
which is the accumulation reading forwards through the build.
A refactor that dropped an edge would shorten those lists and be reviewable in the golden.

```bash
bookshelf record --recipe examples/complex-processing/bookshelf.yaml --version v1.0.0 --bundle /tmp/cp
bookshelf validate /tmp/cp
```
