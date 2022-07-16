"""
Custom exceptions
"""


class UnknownBook(ValueError):
    """
    An unknown book is requested
    """

    pass


class UnknownVersion(ValueError):
    """
    An unknown version is requested
    """

    def __init__(self, name, version):
        self.name = name
        self.version = version

    def __str__(self):
        return f"Could not find {self.name}@{self.version}"
