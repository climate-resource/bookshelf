"""
Functions to run/manage notebooks
"""
import logging
import os
import shutil
from typing import Optional

# pylint: disable=invalid-name
try:
    import jupytext

    has_jupytext = True
except ImportError:  # pragma: no cover
    jupytext = None
    has_jupytext = False
# pylint: disable=invalid-name
try:
    import papermill

    has_papermill = True
except ImportError:  # pragma: no cover
    papermill = None
    has_papermill = False

import yaml

from bookshelf import BookShelf, LocalBook
from bookshelf.constants import PROCESSED_DATA_DIR, ROOT_DIR
from bookshelf.schema import NotebookMetadata

logger = logging.getLogger(__name__)

NOTEBOOK_DIRECTORY = os.path.join(ROOT_DIR, "notebooks")


def load_nb_metadata(
    name: str,
    nb_directory: str = NOTEBOOK_DIRECTORY,
) -> NotebookMetadata:
    """
    Load notebook metadata

    Parameters
    ----------
    name : str
        Filename to load. Should match the notebook name (not checked)
    nb_directory: str
        If a non-absolute path is provided, it is assumed to be relative to nb_directory
    Returns
    -------
    NotebookMetadata
        Metadata about the notebook including the target package and version
    """
    if not (name.endswith(".yaml") or name.endswith(".yml")):
        name = name + ".yaml"

    if not os.path.isabs(name):
        name = os.path.join(nb_directory, name)

    with open(name) as file_handle:
        return NotebookMetadata(**yaml.safe_load(file_handle))


def run_notebook(
    name: str,
    nb_directory: str = NOTEBOOK_DIRECTORY,
    output_directory: Optional[str] = None,
    force: bool = False,
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

    Returns
    -------
    LocalBook
        The generated book
    """
    if not has_papermill:
        raise ImportError(
            "papermill is not installed. Run 'pip install bookshelf[notebooks]'"
        )
    if not has_jupytext:
        raise ImportError(
            "jupytext is not installed. Run 'pip install bookshelf[notebooks]'"
        )

    nb_fname = os.path.join(nb_directory, f"{name}.py")
    metadata_fname = os.path.join(nb_directory, f"{name}.yaml")

    # Verify metadata
    metadata = load_nb_metadata(metadata_fname)
    if metadata.name != name:  # pragma: no cover
        raise ValueError(
            f"name in metadata does not match the name of the notebook "
            f"({metadata.name} != {name}"
        )

    if output_directory is None:
        output_directory = os.path.join(PROCESSED_DATA_DIR, name, metadata.version)
    if os.path.exists(output_directory) and os.listdir(output_directory):
        logger.warning(f"{output_directory} is not empty")
        if not force:
            raise ValueError(f"{output_directory} is not empty")
    os.makedirs(output_directory, exist_ok=True)

    # Copy required files
    logger.info(f"Copying {nb_fname} to {output_directory}")
    shutil.copyfile(nb_fname, os.path.join(output_directory, f"{name}.py"))
    logger.info(f"Copying {metadata_fname} to {output_directory}")
    shutil.copyfile(metadata_fname, os.path.join(output_directory, f"{name}.yaml"))

    # Template and run notebook
    output_nb_fname = os.path.join(output_directory, f"{name}.ipynb")
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
        parameters={"local_bookshelf": output_directory},
    )
    # Attempt to load the book from the output directory
    shelf = BookShelf(path=output_directory)
    book = shelf.load(name, metadata.version)

    logger.info(f"Notebook run successfully with hash: {book.hash()}")
    return book
