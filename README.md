# Bookshelf

<!---
Can use start-after and end-before directives in docs, see
https://myst-parser.readthedocs.io/en/latest/syntax/organising_content.html#inserting-other-documents-directly-into-the-current-document
-->

<!--- sec-begin-description -->

`bookshelf` is how Climate Resource reuses datasets across projects

The `bookshelf` represents a shared collection of curated datasets or `Books`. Each
`Book` is a preprocessed, versioned dataset including the notebooks used to produce it.
As the underlying datasets or processing are updated, new `Books` can be created (with
an updated version). A single dataset may produce multiple `Resources` if different
representations are useful. These `Books` can be deployed to a shared `Bookshelf`
so that they are accessible by other users.

Users are able to use specific `Books` within other projects. The dataset and associated
metadata is fetched and cached locally. Specific versions of `Books` can also be pinned for
reproducibility purposes.

This repository contains the notebooks that are used to generate the `Books`
as well as a CLI tool for managing these datasets.

This is a prototype and will likely change in future. Other potential ideas:

- Deployed data are made available via `api.climateresource.com.au` so that
  they can be consumed queried smartly
- Simple web page to allow querying the data

Each Book consists of a [datapackage](https://specs.frictionlessdata.io/data-package/)
description of the metadata. This datapackage contains the associated `Resources` and
their hashes. Each `Resource` is fetched when it is first used and then cached for later use


<!--- sec-end-description -->

Full documentation can be found at:
[bookshelf.readthedocs.io](https://bookshelf.readthedocs.io/en/latest/).
We recommend reading the docs there because the internal documentation links
don't render correctly on GitLab's viewer.

## Installation

<!--- sec-begin-installation -->

`bookshelf` can be installed via pip:

```bash
pip install bookshelf
```


<!--- sec-end-installation -->

### For developers

<!--- sec-begin-installation-dev -->

For development, we rely on [poetry](https://python-poetry.org) for all our
dependency management. To get started, you will need to make sure that poetry
is installed
([instructions here](https://python-poetry.org/docs/#installing-with-the-official-installer),
we found that pipx and pip worked better to install on a Mac).

For all of work, we use our `Makefile`.
You can read the instructions out and run the commands by hand if you wish,
but we generally discourage this because it can be error prone.
In order to create your environment, run `make virtual-environment`.

If there are any issues, the messages from the `Makefile` should guide you
through. If not, please raise an issue in the [issue tracker][issue_tracker].

For the rest of our developer docs, please see [](development-reference).

[issue_tracker]: https://gitlab.com/climate-resource/bookshelf/bookshelf/issues

<!--- sec-end-installation-dev -->
