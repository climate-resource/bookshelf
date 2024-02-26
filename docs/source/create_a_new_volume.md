# Creating a new volume

## Initial setup

Begin by creating a new folder within the `notebooks` directory. Name this folder after the volume
you wish to create. Copy `simple.py` and `simple.yaml` from the `examples/simple` directory into your
new folder, renaming them to `{volume}.py` and `{volume}.yaml`, respectively. These files will serve
as templates to kickstart your volume creation process.

## Metadata storage

Updating the `{volume}.yaml` with the volume's metadata, this may include:

- name of the volume
- edition
- license
- metadata about author and author_email
- data dictionary
- detailed version information
- etc.

## Logging configuration

Set up the basic configuration for logging:

```python
import logging

logging.basicConfig(level=logging.INFO)
```

## Metadata loading

Load and verify the volume's metadata

```python
from bookshelf.notebook import load_nb_metadata

metadata = load_nb_metadata("volume/volume")
metadata.dict()
```

## Data loading and transformation

Load the data intended for storage in the volume. This data may be sourced locally,
scraped from the web, or downloaded from a server. For data downloads, we recommend
using `pooch` to ensure integrity through hash verification.

Once the data is loaded, perform any necessary manipulations to prepare it for storage.
Convert the data to an `scmdata.ScmRun` object if it isn't already in this format.

## Local book creation

Initialize a local book instance using the prepared metadata:

```python
from bookshelf import LocalBook

# create and return a unique temporary directory
local_bookshelf = tempfile.mkdtemp()

book = LocalBook.create_from_metadata(metadata, local_bookshelf=local_bookshelf)
```

## Resource creation

Add a new `Resource` to the Book utilizing the `scmdata.ScmRun` object. This process involves copying
the timeseries data into a local file, then calculating the hash of the file's contents to ensure data
integrity. Additionally, the timeseries data is transformed into a long format, followed by a hash
calculation of this transformed data. Utilizing these hashes allows for a straightforward verification
process to determine if the files have undergone any modifications.

```python
book.add_timeseries("resource_name", data)
```

Display the `Book`'s metadata, which encompasses all metadata about the Book and its associated
`Resources`:

```python
book.metadata()
```

The metadata outlined above is available for clients to download and use for fetching the `Book`'s
`Resources`. Upon deployment, the Book becomes immutable, meaning any modifications to its metadata
or data necessitate the release of a new Book version.
