"""
Custom exceptions
"""


class UnknownBook(ValueError):
    """
    An unknown book is requested
    """


class UnknownVersion(ValueError):
    """
    An unknown version is requested
    """

    def __init__(self, name: str, version: str | None):
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


class OfflineError(Exception):
    """
    Raised when the network is unavailable and no cached data exists.
    """

    def __init__(self, name: str, version: str | None = None):
        self.name = name
        self.version = version
        if version:
            msg = f"Cannot fetch '{name}' version {version}: network unavailable and not cached locally."
        else:
            msg = f"Cannot fetch '{name}': network unavailable and no cached version found."
        super().__init__(msg)


class UploadError(ValueError):
    """
    Could not upload a book to the remote bookshelf
    """
