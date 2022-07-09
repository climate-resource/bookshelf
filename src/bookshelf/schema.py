from pydantic import BaseModel
from typing import List


class BookVersion(BaseModel):
    version: str
    url: str
    hash: str


class VolumeMeta(BaseModel):
    name: str
    license: str  # A change in license will require a new volume
    versions: List[BookVersion]
