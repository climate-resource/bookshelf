"""
A collection of curated climate data sets
"""

import importlib.metadata

from bookshelf.api import BookshelfAPIClient
from bookshelf.auth import get_token, is_authenticated
from bookshelf.book import LocalBook
from bookshelf.shelf import BookShelf

__version__ = importlib.metadata.version("bookshelf")

__all__ = [
    "BookShelf",
    "LocalBook",
    "BookshelfAPIClient",
    "is_authenticated",
    "get_token",
    "__version__",
]
