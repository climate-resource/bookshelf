"""
Bookshelf, Climate Resource's curated datasets
See README and docs for more info.
"""


try:
    from importlib.metadata import version as _version
except ImportError:  # pragma: no cover
    # no recourse if the fallback isn't there either...
    from importlib_metadata import version as _version  # type: ignore

try:
    __version__ = _version("bookshelf")
except Exception:  # pragma: no cover pylint: disable=broad-except
    # Local copy, not installed with setuptools
    __version__ = "unknown"


from bookshelf.book import LocalBook  # noqa
from bookshelf.shelf import BookShelf  # noqa
