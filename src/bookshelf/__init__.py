"""
A collection of curated climate data sets
"""
import importlib.metadata

__version__ = importlib.metadata.version("bookshelf")


from bookshelf.book import LocalBook  # noqa pylint: disable=wrong-import-position
from bookshelf.shelf import BookShelf  # noqa  pylint: disable=wrong-import-position
