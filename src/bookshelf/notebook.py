import yaml

from bookshelf.schema import NotebookMetadata


def load_nb_metadata(name: str) -> NotebookMetadata:
    """
    Load notebook metadata

    Parameters
    ----------
    name : str
        Filename to load. Should match t

    Returns
    -------
    NotebookMetadata
        Metadata about the notebook including the target package and version
    """
    if not (name.endswith(".yaml") or name.endswith(".yml")):
        name = name + ".yaml"
    with open(name) as file_handle:
        return NotebookMetadata(**yaml.safe_load(file_handle))
