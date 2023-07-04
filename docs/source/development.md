(development-reference)=
# Development

Notes for developers. If you want to get involved, please do!

## Versioning

This package follows the version format described in
[PEP440](https://peps.python.org/pep-0440/) and
[Semantic Versioning](https://semver.org/). Since our commit messages are
written to follow the
[conventional commits](https://www.conventionalcommits.org/en/v1.0.0/)
specification, comitizen can use the commit messages since the last release to
determine whether a major, minor or patch release is required automatically.
See the docs for the
[commitizen bump](https://commitizen-tools.github.io/commitizen/bump/)
command for additional details about the version bumping process and
[](releasing-reference) for additional details about how we do releases in
this project.

(releasing-reference)=
## Releasing

### Standard process

Releasing is semi-automated. The steps required are the following:


1. Bump the version: manually trigger the "bump" stage from the latest commit
   in main (pipelines are here:
   https://gitlab.com/climate-resource/bookshelf/bookshelf/-/pipelines).
   This will then trigger a release, including publication to PyPI.

1. Download the artifacts from the release job. The `release_notes.md` artifact
   will be pre-filled with the list of changes included in this release. You find it
   in the release-bundle zip file at
   [the artifacts section](https://gitlab.com/climate-resource/bookshelf/bookshelf/-/artifacts). The
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
