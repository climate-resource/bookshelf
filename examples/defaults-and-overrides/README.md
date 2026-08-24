# `defaults-and-overrides`

What a book inherits from `defaults:`, and what it replaces.

The merge is field by field rather than section by section.
A book that states one discovery field keeps the rest of the defaults,
so `v2.0.0` replacing `description`, `publisher` and `authors`
still carries the `title`, `homepage_url` and `methodology_url` the defaults state.

`defaults.resources:` is a template rather than an addition.
Both books name `raw`, so both get the default `type: tabular`,
and `v2.0.0` states `type: timeseries` for the same name to override it.
A book that never named `raw` would not get it,
because a default that could add a resource would hide what a build reads from the book itself.

The two goldens are the point of the example.
`expected/v1.0.0/manifest.lock` shows the inherited values and
`expected/v2.0.0/manifest.lock` shows the overridden ones beside the fields that were left alone.
The recorder bakes the effective values onto the book, so the manifest is where inheritance is visible.

```bash
bookshelf record --recipe examples/defaults-and-overrides/bookshelf.yaml --version v1.0.0 --bundle /tmp/dao1
bookshelf record --recipe examples/defaults-and-overrides/bookshelf.yaml --version v2.0.0 --bundle /tmp/dao2
```
