"""
Bookshelf utilities
"""
import logging
import os
import pathlib
from typing import Any, Optional, Union

import appdirs
import pooch

from bookshelf.constants import DATA_FORMAT_VERSION, DEFAULT_BOOKSHELF, ENV_PREFIX

logger = logging.getLogger(__file__)


def default_cache_location() -> str:
    r"""
    Determine the default cache location

    By default, local Books are stored in the default cache location unless overridden for
    a given :class:`bookshelf.BookShelf`. The default cache location is determined using
    the ``BOOKSHELF_CACHE_LOCATION`` or if that environment variable is not present, it
    falls back to an operating specific location. This location is determined using
    `appdirs <https://github.com/ActiveState/appdirs>`__ and may look like the following:

    * Mac: ``~/Library/Caches/bookshelf``
    * Unix: ``~/.cache/bookshelf`` or the value of the ``XDG_CACHE_HOME``
      environment variable, if defined.
    * Windows: ``C:\Users\<user>\AppData\Local\bookshelf\Cache``

    Returns
    -------
    str
        The default cache location
    """
    return os.environ.get(
        "BOOKSHELF_CACHE_LOCATION",
        appdirs.user_cache_dir("bookshelf", appauthor=False),
    )


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


def build_url(bookshelf: str, *paths: str) -> str:
    """
    Build a URL

    Parameters
    ----------
    bookshelf: str
        The remote bookshelf
    paths : list of str
        A collection of paths that form the path of the URL
    Returns
    -------
    str
        The merged URL

    """
    return "/".join([bookshelf, *paths])


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
    if not force and local_fname.exists():
        if pooch.hashes.hash_matches(local_fname, known_hash):
            return
        raise ValueError(
            f"Hash for existing file {local_fname} does not match the expected "
            f"value {known_hash}"
        )

    if force or not local_fname.exists():
        download(url, local_fname=local_fname, known_hash=known_hash)
        logger.info(f"{local_fname} downloaded from {url}")

    if not local_fname.exists():
        raise FileNotFoundError(f"Could not find file {local_fname}")  # pragma: no cover


def get_env_var(
    name: str,
    add_prefix: bool = True,
    raise_on_missing: bool = True,
    default: Any = None,
) -> str:
    """
    Get an environment variable value

    If the variable isn't set raise an exception if ``raise_on_missing`` is ``True``

    Parameters
    ----------
    name : str
        Environment variable name to check
    add_prefix : bool
        If ``True``, prefix the environment variable name with  ``bookshelf.constants.ENV_PREFIX``
    raise_on_missing : bool
        If ``True``, a ValueError is raised
    default : Any
        Value to return if the environment variable is missing and ``raise_on_missing`` is ``True``
    Returns
    -------
    str
        Value of environment variable

    Raises
    ------
    ValueError
        Environment variable not set
    """
    if add_prefix:
        name = ENV_PREFIX + name
    name = name.upper()
    if raise_on_missing and name not in os.environ:
        raise ValueError(f"Environment variable {name} not set. Check configuration")
    return os.environ.get(name, default)


def get_remote_bookshelf(bookshelf: Optional[str]) -> str:
    """
    Get the remote bookshelf URL

    If no bookshelf is provided, use the ``BOOKSHELF_REMOTE`` environment variable, or,
    the ``bookshop.constants.DEFAULT_BOOKSHELF`` parameter if the environment variable
    is not present.

    Parameters
    ----------
    bookshelf : str
        URL for the bookshelf

        If not provided the URL is determined as above

    Returns
    -------
    str
        URL for the remote bookshelf
    """
    if bookshelf is None:
        return os.environ.get(ENV_PREFIX + "REMOTE", DEFAULT_BOOKSHELF)
    return bookshelf
