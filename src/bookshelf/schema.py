"""
Schema
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel  # pylint: disable=no-name-in-module

Version = Optional[str]


class BookVersion(BaseModel):
    """
    Version information for a book
    """

    version: str
    url: str
    hash: str


class VolumeMeta(BaseModel):
    """
    Schema for a given Volume (A collection of Books with the same name)
    """

    name: str
    license: str  # A change in license will require a new volume
    versions: List[BookVersion]


class NotebookMetadata(BaseModel):
    """
    Schema for a given Volume (A collection of Books with the same name)
    """

    name: str
    version: str
    description: Optional[str]
    license: str
    metadata: Dict[str, Any]  # TODO: type this
    dataset: Optional[Dict[str, Any]]  # TODO: type this
