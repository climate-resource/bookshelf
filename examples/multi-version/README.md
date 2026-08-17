# `multi-version`

The shape a real feedstock takes: one recipe, one build file, and several upstream versions.

`bookshelf record --version` selects the book to build, and it is required.
A bare `record` exits non-zero and names the versions the recipe declares, because there is no
default version and picking one would be a guess.

Books do not inherit from each other.
Each restates its `resources` and its `license` in full, so a reader never has to walk backwards
through the file to learn what a version is built from.
`v2.0.0` states a `release_date` that `v1.0.0` does not, which is visible in the two manifests.

```bash
bookshelf record --recipe examples/multi-version/bookshelf.yaml --version v1.0.0 --bundle /tmp/mv1
bookshelf record --recipe examples/multi-version/bookshelf.yaml --version v2.0.0 --bundle /tmp/mv2
```
