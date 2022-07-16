"""
Schema
"""
from typing import List

from pydantic import BaseModel


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
