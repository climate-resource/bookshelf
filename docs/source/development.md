(development-reference)=
# Development

Notes for developers. If you want to get involved, please do!

## Installation

```{include} ../../README.md
:start-after: <!--- sec-begin-installation-dev -->
:end-before: <!--- sec-end-installation-dev -->
```

## Language

We use British English for our development.
We do this for consistency with the broader work context of our lead developers.

## Versioning

This package follows the version format described in [PEP440](https://peps.python.org/pep-0440/) and
[Semantic Versioning](https://semver.org/) to describe how the version should change depending on the updates to the
code base. Our commit messages are written using written to follow the
[conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) standard which makes it easy to find the
commits that matter when traversing through the commit history.

(releasing-reference)=
## Releasing

Releasing is semi-automated via a CI job. The CI job requires the type of version bump that will be performed to be
manually specified. See the poetry docs for the [list of available bump rules](https://python-poetry.org/docs/cli/#version).

### Standard process

The steps required are the following:


1. Bump the version: manually trigger the "bump" stage from the latest commit
   in main (pipelines are [here](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/pipelines)).
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

## Read the Docs

Our documentation is hosted by
[Read the Docs (RtD)](https://www.readthedocs.org/), a service for which we are
very grateful. The RtD configuration can be found in the `.readthedocs.yaml`
file in the root of this repository. The docs are automatically
deployed at
[bookshelf.readthedocs.io](https://bookshelf.readthedocs.io/en/latest/).
