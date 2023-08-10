(notebooks-reference)=
# Notebooks

Here we provide various examples of how to use bookshelf.
They  are derived from
[jupyter notebooks](https://docs.jupyter.org/en/latest/start/index.html),
but are saved using [jupytext](https://jupytext.readthedocs.io/en/latest/)
to keep our repository slim and make it easier to track changes.

## Basic demos

```{toctree}
:caption: Contents
:maxdepth: 1
notebooks/basic-demo.py
```

## Notebook execution info

```{nb-exec-table}
```

## Notebooks creating the `Book`s

The directory `notebooks` contains the notebooks used to produce the `Book`s. Each
notebook  corresponds with a single `Volume` (collection of `Book`s with the same
`name`).

Each notebook also has a corresponding `.yaml` file containing the latest metadata
for the `Book`. See the `NotebookMetadata` schema(`bookshelf.schema.NotebookMetadata`)
for the expected format of this file.

## Creating a new `Volume`

* Start by copying `example.py` and `example.yaml` and renaming to the name of
  the new volume. This provides a simple example to get started.
* Update `{volume}.yaml` with the correct metadata
* Update the fetch and processing steps as needed, adding additional `Resource`s
  to the `Book` as needed.
* Run the notebook and check the output
* **TODO** Perform the release procedure to upload the built book to the remote
  `BookShelf`
  `bookshelf save {volume}`

## Updating a `Volume`'s version

* Update the `version` attribute in the metadata file
* Modify other metadata attributes as needed
* Update the data fetching and processing steps in the notebook
* Run the notebook and check the output
* **TODO** Perform the release procedure to upload the built book to the remote
  `BookShelf`

## Testing a notebook locally

You can run a notebook with a specified output directory for local testing:
```bash
poetry run bookshelf run --output /path/to/custom/directory <notebook_name>
```

The generated book can then be used directly from the local directory.
Note that the path to the custom directory needs to specify the `version` of the
Book.
When loading the Book, you must also specify the version and the edition otherwise it
will query the remote bookshelf.

```python
import bookshelf

shelf = bookshelf.BookShelf("/path/to/custom/directory/{version}")

new_book = shelf.load("{notebook_name}", version="{version}", edition=edition)
```
When updating an existing Book, remember to increase the version or the edition to make
sure you load your newly generated data, not the old data.
