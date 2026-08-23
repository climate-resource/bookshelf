# `low-level-api`

Publishing from a script that was never written around Bookshelf.

Every other example here is a recipe and a build file driven by `bookshelf record`.
That suits a feedstock whose whole reason to exist is the book it produces.
It suits a long-running pipeline much less well, because there the publishing step is a small
tail on a script that already has its own command line, its own inputs and its own outputs.

`record.py` is such a script.
It loads a station file, complains about the ones it cannot use, drops the flagged readings,
averages them by year and writes a run summary.
None of that involves Bookshelf, and passing no `--bundle` runs the whole pipeline without
importing the SDK at all.

```bash
python examples/low-level-api/record.py --report /tmp/summary.txt
```

The recording is the `record` function, and it is the only part that touches the SDK.

- `RecordingBookshelf` is the ordinary `Bookshelf` facade with the producer seam rebound,
  so `activity()`, `draft_book()` and `register_external()` land in a bundle rather than reaching
  the API. Recording needs no credentials. Replaying the bundle afterwards is the half that does.
- The book is framed first, because its visibility becomes the default for what follows.
- `activity()` is opened explicitly rather than through the `book.write` sugar,
  which is what lets the script state `code_ref`, `runner` and `config` itself.
- `attach` and `publish` are separate editorial calls, and under a recording `publish` marks the
  book for publication during replay rather than publishing anything now.

```bash
python examples/low-level-api/record.py --bundle /tmp/llapi
bookshelf validate /tmp/llapi
```

The runner discovers this example by its `record.py` rather than by a recipe, runs it the way a
user would, and compares the bundle it records against `expected/` like any other example.
