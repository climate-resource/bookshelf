"""
A collection of curated climate data sets
"""
import importlib.metadata

from bookshelf.book import LocalBook
from bookshelf.shelf import BookShelf

__version__ = importlib.metadata.version("bookshelf")

__all__ = ["LocalBook", "BookShelf"]
