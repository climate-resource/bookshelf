Configuration
=============


Environment Variables
---------------------

Environment variables are used to control some aspects of the model. The default values
for these environment variables are generally suitable, but if you require updating
these values we recommend the use of a ``.env`` file to make the changes easier to
reproduce in future.

.. envvar:: BOOKSHELF_REMOTE

  The remote URL for the the bookshelf

  This defaults to a Climate Resource specific URL, but can be used to point to an
  alternative bookshelf. For example a staging/testing bookshelf for prereleased Books.

.. envvar:: BOOKSHELF_CACHE_LOCATION

  Local directory used to cache any Books fetched from a remote bookshelf. This cache
  can be cleared using the ``clear`` CLI command.

.. envvar:: BOOKSHELF_DOWNLOAD_CACHE_LOCATION

  Override the default download location for any raw data downloads

.. envvar:: BOOKSHELF_NOTEBOOK_DIRECTORY

  Search location for the notebooks used to generate books
