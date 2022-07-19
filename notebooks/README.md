# Notebooks

This directory contains the notebooks used to produce the `Book`s. Each notebook
corresponds with a single `Volume` (collection of `Book`s with the same `name`).

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
