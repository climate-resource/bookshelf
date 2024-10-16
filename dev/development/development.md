# Development

Notes for developers. If you want to get involved, please do!
We welcome all kinds of contributions, for example:

- docs fixes/clarifications
- bug reports
- bug fixes
- feature requests
- pull requests
- tutorials

## Workflows

<!---
Note: will make more sense once we have a copier template again.
This section was auto-generated by the copier template
and the text below is just a placeholder to get you started.
The workflows section will likely need to be updated
to be project specific as the project's norms are established.
-->

We don't mind whether you use a branching or forking workflow.
However, please only push to your own branches,
pushing to other people's branches is often a recipe for disaster,
is never required in our experience
so is best avoided.

Try and keep your merge requests as small as possible
(focus on one thing if you can).
This makes life much easier for reviewers
which allows contributions to be accepted at a faster rate.

## Installation

---8<--- "README.md:getting-started-dev"

## Language

We use British English for our development.
We do this for consistency with the broader work context of our lead developers.

## Versioning

This package follows the version format
described in [PEP440](https://peps.python.org/pep-0440/)
and [Semantic Versioning](https://semver.org/)
to describe how the version should change
depending on the updates to the code base.

Our commit messages are written using written
to follow the
[conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) standard which makes it easy to find the
commits that matter when traversing through the commit history.

/// admonition | Note
We don't use the commit messages from conventional commits
to automatically generate the changelog and release documentation.
///

## The notebooks generating the datasets

The top-level directory `notebooks` contains the notebooks used to produce the `Book`s.
Each  notebook  corresponds with a single `Volume` (collection of `Book`s with the same
`name`).

Each notebook also has a corresponding `.yaml` file containing the latest metadata
for the `Book`. See the `NotebookMetadata` schema(`bookshelf.schema.NotebookMetadata`)
for the expected format of this file.

### Creating a new `Volume`

* Start by copying `example.py` and `example.yaml` and renaming to the name of
  the new volume. This provides a simple example to get started.
* Update `{volume}.yaml` with the correct metadata
* Update the fetch and processing steps as needed, adding additional `Resource`s
  to the `Book` as needed.
* Run the notebook and check the output
* **TODO** Perform the release procedure to upload the built book to the remote
  `BookShelf`
  `bookshelf save {volume}`

### Updating a `Volume`'s version

* Update the `version` attribute in the metadata file
* Modify other metadata attributes as needed
* Update the data fetching and processing steps in the notebook
* Run the notebook and check the output
* **TODO** Perform the release procedure to upload the built book to the remote
  `BookShelf`

### Testing a notebook locally

You can run a notebook with a specified output directory for local testing:
```bash
uv run bookshelf run --output /path/to/custom/directory <notebook_name>
```

The generated book can then be used directly from the local directory.
Note that the path to the custom directory needs to specify the `version` of the
Book.
When loading the Book, you must also specify the version and the edition otherwise it
will query the remote bookshelf.

```python
import bookshelf

shelf = bookshelf.BookShelf("/path/to/custom/directory/{version}")
edition = 1

new_book = shelf.load("{notebook_name}", version="{version}", edition=edition)
```
When updating an existing Book, remember to increase the version or the edition to make
sure you load your newly generated data, not the old data.

## Releasing

Releasing is semi-automated via a CI job. The CI job requires the type of version bump that will be performed to be
manually specified. See the poetry docs for the [list of available bump rules](https://python-poetry.org/docs/cli/#version).

### Standard process

The steps required are the following:

1. Bump the version: manually trigger the "bump" stage from the latest commit
   in main (pipelines are [here](https://github.com/climate-resource/bookshelf/-/pipelines)).
   A valid "bump_rule" (see https://python-poetry.org/docs/cli/#version)
   will need to be specified via the "BUMP_RULE" CI
   variable (see https://docs.gitlab.com/ee/ci/variables/). This will then
   trigger a release, including publication to PyPI.

1. Download the artefacts from the release job. The `release_notes.md` artefact
   will be pre-filled with the list of changes included in this release. You find it
   in the release-bundle zip file at
   [the artefacts section](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/artifacts). The
   announcements section should be completed manually to highlight any
   particularly notable changes or other announcements (or deleted if not
   relevant for this release).

1. Once the release notes are filled out, use them to make a
   [release](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/releases/new).


1. That's it, release done, make noise on social media of choice, do whatever
   else

1. Enjoy the newly available version