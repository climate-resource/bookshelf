"""
Custom exceptions
"""

from typing import Optional


class UnknownBook(ValueError):
    """
    An unknown book is requested
    """


class UnknownVersion(ValueError):
    """
    An unknown version is requested
    """

    def __init__(self, name: str, version: Optional[str]):
        self.name = name
        self.version = version
        super().__init__()

    def __str__(self) -> str:
        return f"Could not find {self.name}@{self.version}"


class UnknownEdition(UnknownVersion):
    """
    An unknown edition is requested
    """

    def __init__(self, name: str, version: str, edition: int):
        super().__init__(name, version)
        self.edition = edition

    def __str__(self) -> str:
        return f"Could not find {self.name}@{self.version} ed.{self.version}"


class UploadError(ValueError):
    """
    Could not upload a book to the remote bookshelf
    """
