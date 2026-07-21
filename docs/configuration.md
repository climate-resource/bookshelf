# Configuration

## Environment Variables

Environment variables are used to control some aspects of the model.
The default values for these environment variables are generally suitable,
but if you require updating these values we recommend the use of a `.env` file
to make the changes easier to reproduce in future.

### `BOOKSHELF_REMOTE`

The URL for the remote bookshelf

This defaults to a Climate Resource specific URL,
but can be used to point to an alternative bookshelf.
For example a staging/testing bookshelf for prereleased Books.

### `BOOKSHELF_CACHE_LOCATION`

Local directory used to cache any Books fetched from a remote bookshelf.
This cache can be cleared using the `bookshelf clear` command.

### `BOOKSHELF_DOWNLOAD_CACHE_LOCATION`

Override the default download location for any raw data downloads

### `BOOKSHELF_NOTEBOOK_DIRECTORY`

Search location for the notebooks used to generate books
