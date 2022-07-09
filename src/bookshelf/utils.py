import pathlib
import os
import urllib.parse

import pooch
from bookshelf.constants import DATA_FORMAT_VERSION


def create_local_cache(path: [str, pathlib.Path] = None) -> pathlib.Path:
    """
    Prepare a cache directory

    Creates a writeable directory in a platform-specific way (see pooch.utils.os_cache)

    Parameters
    ----------
    path: str or path
        If provided, override the default cache location

    Returns
    -------
    pathlib.Path

    Location of a writable local cache
    """
    if path is None:
        path = pooch.utils.os_cache("bookshelf")

    path = pooch.utils.cache_location(path / DATA_FORMAT_VERSION)

    pooch.utils.make_local_storage(path)

    return path


def download(
    url: str,
    local_fname: pathlib.Path,
    known_hash: str = None,
    progressbar: bool = False,
    retry_count: int = 0,
):
    """
    Download a remote file using pooch's downloader

    Parameters
    ----------
    url: str
        URL to download
    local_fname
        Path where the result will be stored
    known_hash
    progressbar: bool
        If true, show a progress bar showing the download process
    retry_count: int
        The number of retries to attempt
    """
    downloader = pooch.core.choose_downloader(url, progressbar=progressbar)
    pooch.core.stream_download(
        url,
        fname=local_fname,
        known_hash=known_hash,
        downloader=downloader,
        retry_if_failed=retry_count,
    )


def build_url(bookshelf, *paths) -> str:
    return os.path.join(bookshelf, *paths)
