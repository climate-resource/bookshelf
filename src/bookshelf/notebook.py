"""
Functions to run/manage notebooks
"""
import logging
import os
import shutil
from typing import Any, Optional

try:
    import jupytext

    has_jupytext = True
except ImportError:  # pragma: no cover
    jupytext = None
    has_jupytext = False
try:
    import papermill

    has_papermill = True
except ImportError:  # pragma: no cover
    papermill = None
    has_papermill = False

import yaml

from bookshelf import BookShelf, LocalBook
from bookshelf.constants import PROCESSED_DATA_DIR, ROOT_DIR
from bookshelf.errors import UnknownVersion
from bookshelf.schema import ConfigSchema, NotebookMetadata, Version
from bookshelf.utils import get_env_var

logger = logging.getLogger(__name__)


def get_notebook_directory(nb_dir: Optional[str] = None) -> str:
    """
    Get the root location of the notebooks used to generate books

    The order of lookup is (in increasing precedence):

    * default ("/notebooks" in a locally checked out version of the repository)
    * ``BOOKSHELF_NOTEBOOK_DIRECTORY`` environment variable
    * ``nb_dir`` parameter

    Parameters
    ----------
    nb_dir : str
        If provided override the default value

    Returns
    -------
    str
        Location of notebooks

    """
    if nb_dir:
        return nb_dir

    try:
        nb_directory = get_env_var("NOTEBOOK_DIRECTORY")
    except ValueError:
        nb_directory = os.path.join(ROOT_DIR, "notebooks")

    return nb_directory


def _load_nb_config(
    name: str,
    nb_directory: Optional[str] = None,
) -> tuple[ConfigSchema, dict[str, Any]]:
    nb_directory = get_notebook_directory(nb_directory)

    metadata_fname = name
    if nb_directory and not os.path.isabs(name):
        metadata_fname = os.path.join(nb_directory, name)

    # If a directory is provided assume that the config is similarly named
    if os.path.isdir(metadata_fname):
        metadata_fname = os.path.join(metadata_fname, name.split("/")[-1] + ".yaml")

    if not metadata_fname.endswith(".yaml") and not metadata_fname.endswith(".yml"):
        metadata_fname = metadata_fname + ".yaml"

    if not os.path.exists(metadata_fname):
        raise FileNotFoundError(f"Could not find {metadata_fname}")

    with open(metadata_fname) as file_handle:
        data = yaml.safe_load(file_handle)

        # always override with the file that was used
        data["source_file"] = metadata_fname
        return ConfigSchema(**data), data


def load_nb_metadata(
    name: str,
    version: Optional[Version] = None,
    nb_directory: Optional[str] = None,
) -> NotebookMetadata:
    """
    Load notebook metadata

    Attempts to search {param}`nb_directory` for a metadata YAML file. This YAML file
    contains information about the dataset that is being processed. See NotebookMetadata
    for a description of the available options.

    The assumed filename format for versioned data is {name}_{version}.yaml where
    name matches the notebook name and the name as specified in the NotebookMetadata

    Parameters
    ----------
    name : str
        Filename to load. Should match the notebook name (not checked)
    version : str
        Version of the metadata to load. If none is provided, the last version will be used
    nb_directory: str
        If a non-absolute path is provided, it is assumed to be relative to nb_directory

    Raises
    ------
    UnknownVersion
        A matching version is not in the configuration

    Returns
    -------
    NotebookMetadata
        Metadata about the notebook including the target package and version
    """
    config, raw_data = _load_nb_config(name, nb_directory)

    if "version" in raw_data and version != raw_data["version"]:
        # Check if a version has already been selected
        raise ValueError("Requested version does not match the metadata")

    if version:
        selected_version = None
        for v in config.versions:
            if v.version == version:
                selected_version = v
    else:
        selected_version = config.versions[-1]
    if selected_version is None:
        raise UnknownVersion(config.name, version)

    return NotebookMetadata(**raw_data, **selected_version.dict())


def run_notebook(
    name: str,
    nb_directory: Optional[str] = None,
    output_directory: Optional[str] = None,
    force: bool = False,
    version: Optional[Version] = None,
) -> LocalBook:
    """
    Run a notebook to generate a new Book

    The jupytext ``.py`` version of the notebook is used.

    The template file and configuration is copied to the output directory. The
    template ``.py`` file is then used to create a notebook which is run using
    ``papermill``. The ``local_bookshelf`` parameter is also set to the output
    directory.

    Parameters
    ----------
    name : str
        Name of the notebook
    nb_directory : str
        Directory containing the notebooks.

        This defaults to the ``notebooks/`` directory in this project
    output_directory : str
        Where the output directory will be created.

        This defaults to ``data/processing/{name}/{version}``
    force : bool
        If True, override the existing data in the output directory
    version : str
        Version to extract

    Returns
    -------
    LocalBook
        The generated book
    """
    if not has_papermill:
        raise ImportError("papermill is not installed. Run 'pip install bookshelf[notebooks]'")
    if not has_jupytext:
        raise ImportError("jupytext is not installed. Run 'pip install bookshelf[notebooks]'")

    short_name = name.split("/")[-1]

    # Verify metadata
    metadata = load_nb_metadata(name, version=version, nb_directory=nb_directory)
    nb_fname = metadata.source_file.replace(".yaml", ".py")

    if not os.path.exists(nb_fname):
        raise FileNotFoundError(f"Could not find notebook: {nb_fname}")

    logger.info(f"Loaded metadata from {metadata.source_file}")
    if metadata.name != short_name:  # pragma: no cover
        raise ValueError(
            "name in metadata does not match the name of the notebook "
            f"({metadata.name} != {name}"
        )
    logger.info(f"Processing {metadata.long_name()}")

    if output_directory is None:
        output_directory = os.path.join(PROCESSED_DATA_DIR, short_name)

    output_directory = os.path.join(output_directory, metadata.version)
    if os.path.exists(output_directory) and os.listdir(output_directory):
        logger.warning(f"{output_directory} is not empty")
        if not force:
            raise ValueError(f"{output_directory} is not empty")
    os.makedirs(output_directory, exist_ok=True)

    # Copy required files
    logger.info(f"Copying {nb_fname} to {output_directory}")
    shutil.copyfile(nb_fname, os.path.join(output_directory, f"{short_name}.py"))
    logger.info(f"Copying metadata to {output_directory}")
    with open(os.path.join(output_directory, f"{short_name}.yaml"), "w") as fh:
        yaml.safe_dump(metadata.dict(), fh)

    # Template and run notebook
    output_nb_fname = os.path.join(output_directory, f"{short_name}.ipynb")
    logger.info(f"Creating notebook {output_nb_fname} from {nb_fname}")
    notebook_jupytext = jupytext.read(nb_fname)
    jupytext.write(
        notebook_jupytext,
        output_nb_fname,
        fmt="ipynb",
    )
    papermill.execute_notebook(
        output_nb_fname,
        output_nb_fname,
        parameters={"local_bookshelf": output_directory, "version": version},
    )
    # Attempt to load the book from the output directory
    shelf = BookShelf(path=output_directory)
    book = shelf.load(short_name, metadata.version, edition=metadata.edition)

    logger.info(f"Notebook run successfully with hash: {book.hash()}")
    return book


def get_available_versions(name: str, include_private: bool = False) -> tuple[str, ...]:
    """
    Get a list of available versions of a book

    Parameters
    ----------
    name
        Package name
    include_private
        If True, also include private versions

    Returns
    -------
        List of versions
    """
    config, _ = _load_nb_config(name)

    versions = config.versions
    if not include_private:
        versions = [v for v in versions if not v.private]

    return tuple(v.version for v in versions)
