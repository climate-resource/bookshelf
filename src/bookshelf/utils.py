"""
Bookshelf utilities
"""
import logging
import os
import pathlib
from typing import Optional, Union

import pooch

from bookshelf.constants import DATA_FORMAT_VERSION

logger = logging.getLogger(__file__)


def default_cache_location():
    return os.environ.get("BOOKSHELF_CACHE_LOCATION", pooch.utils.os_cache("bookshelf"))


def create_local_cache(path: Union[str, pathlib.Path, None] = None) -> pathlib.Path:
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
        path = default_cache_location()

    path = pooch.utils.cache_location(pathlib.Path(path) / DATA_FORMAT_VERSION)

    pooch.utils.make_local_storage(path)

    return pathlib.Path(path)  # type: ignore


def download(
    url: str,
    local_fname: pathlib.Path,
    known_hash: Optional[str] = None,
    progressbar: bool = False,
    retry_count: int = 0,
) -> None:
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


def build_url(bookshelf: str, *paths: Union[str, pathlib.Path]) -> str:
    """
    Build a URL

    Parameters
    ----------
    bookshelf: str
        The remote bookshelf
    paths : list of str or pathlib.Path
        A collection of paths that form the path of the URL
    Returns
    -------
    str
        The merged URL

    """
    return os.path.join(bookshelf, *paths)


def fetch_file(
    url: str,
    local_fname: pathlib.Path,
    known_hash: Optional[str] = None,
    force: Optional[bool] = False,
) -> None:
    """
    Fetch a remote file and store it locally

    Parameters
    ----------
    url : str
        URL of data file
    local_fname : pathlib.Path
        The location of where to store the downloaded file
    known_hash : str
        Expected sha256 has of the output file.

        If the hash of the downloaded file doesn't match the expected hash a ValueError
        is raised.

        If no hash is provided, no checks are performed
    force : bool
        If True, always download the file

    Raises
    ------
    ValueError
        Failing hash check for the output file
    FileNotFoundError
        Downloaded file was not in the expected location

    """
    existing_hash = None
    if not force and local_fname.exists():
        if pooch.hashes.hash_matches(local_fname, known_hash):
            return
        raise ValueError(
            f"Hash for existing file {local_fname} does not match the expected "
            f"value {known_hash}"
        )

    if force or existing_hash is None:
        download(url, local_fname=local_fname, known_hash=known_hash)
        logger.info(f"{local_fname} downloaded from {url}")

    if not local_fname.exists():
        raise FileNotFoundError(f"Could not find file {local_fname}")  # noqa
