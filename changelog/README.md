# Changelog

This directory contains news fragments.
These are short markdown files that are assembled into the changelog
the next time a release is cut.

The changelog is read by users of `bookshelf`,
so write for them rather than describing internal changes.
The git history and the pull requests already cover the developer view.

Use the past tense and punctuate properly:

```
Improved verbose diff output with sequences.

Terminal summary statistics now use multiple colours.
```

Each file is named `<PR>.<TYPE>.md`, where `<PR>` is the pull request number
and `<TYPE>` is one of:

* `feature`: new user facing features, like new command line options and new behaviour.
* `improvement`: improvement of existing functionality, usually without requiring user intervention.
* `fix`: fixes a bug.
* `docs`: documentation improvement, like rewording a section or adding missing docs.
* `deprecation`: feature deprecation.
* `breaking`: a change which may break existing uses, such as feature removal or behaviour change.
* `trivial`: a small typo or internal change that might be noteworthy.

For example: `123.feature.md`, `456.fix.md`.

You need the pull request number for the filename, so open the pull request first.
A single pull request can carry more than one fragment,
for example when it adds a feature and deprecates something at the same time.

If you are not sure which type to use, ask in the pull request.

`towncrier` preserves multiple paragraphs and formatting such as code blocks and lists.
For anything other than a feature it is usually better to stick to one paragraph.

Run `make changelog-draft` to preview what will be added to
[docs/changelog.md](../docs/changelog.md) on the next release.
