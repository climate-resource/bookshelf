# CHANGELOG
This directory contains "news fragments" which are short files that contain a small `Markdown`-formatted text that will be
added to the next `CHANGELOG`.

The CHANGELOG will be read by users, so this description should be aimed to `ndc-quantification` users instead of
describing internal changes which are only relevant to the developers. Merge requests in combination with our git history,
which follows [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/#summary), provides additional
developer-centric information.

Make sure to use full sentences in the past tense and use punctuation, examples:

```
Improved verbose diff output with sequences.

Terminal summary statistics now use multiple colors.
```


Each file should be named like `<MR>.<TYPE>.md`, where `<MR>` is the merge request number, and `<TYPE>` is one of:

* `feature`: new user facing features, like new command-line options and new behavior.
* `improvement`: improvement of existing functionality, usually without requiring user intervention
* `fix`: fixes a bug.
* `docs`: documentation improvement, like rewording an entire session or adding missing docs.
* `deprecation`: feature deprecation.
* `breaking`: a change which may break existing suites, such as feature removal or behavior change.
* `trivial`: fixing a small typo or internal change that might be noteworthy.

So for example: `123.feature.md`, `456.fix.md`.

Since you need the merge request number for the filename, you must submit a MR and then get the MR number so you can add a
changelog using that. A single MR can also have multiple news items, for example a given MR may add a feature as well as
deprecate some existing functionality.

If you are not sure what issue type to use, don't hesitate to ask in your MR.

`towncrier` preserves multiple paragraphs and formatting (code blocks, lists, and so on), but for entries other than
features it is usually better to stick to a single paragraph to keep it concise. You may also use `MyST` [style
cross-referencing](https://myst-parser.readthedocs.io/en/latest/syntax/cross-referencing.html) to link to other
documentation.

You can also run `towncrier --draft` to see the draft changelog that will be appended to [docs/source/changelog.md]()
on the next release.
