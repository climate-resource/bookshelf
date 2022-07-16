from typing import List

from pydantic import BaseModel


class BookVersion(BaseModel):
    version: str
    url: str
    hash: str


class VolumeMeta(BaseModel):
    name: str
    license: str  # A change in license will require a new volume
    versions: List[BookVersion]
