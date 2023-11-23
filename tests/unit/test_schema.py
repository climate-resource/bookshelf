import pytest

from bookshelf.schema import DatasetMetadata, NotebookMetadata


def test_file():
    res = DatasetMetadata(author="test")
    assert res.files == []


@pytest.mark.parametrize("idx", (None, 0, -1))
def test_download_files(idx):
    # doesn't trigger pooch.retrieve
    # TODO: add tests for pooch functionality
    nb_metadata = NotebookMetadata(
        name="test",
        version="v1.0.0",
        edition=1,
        license="unspecified",
        source_file="",
        private=False,
        metadata={},
        dataset={
            "author": "test",
            "files": [{"url": "file://local/filename.txt", "hash": "myhash"}],
        },
    )

    if idx:
        res = nb_metadata.download_file(idx)
    else:
        res = nb_metadata.download_file()

    assert res == "local/filename.txt"


@pytest.mark.parametrize("idx", (-100, 999))
def test_download_files_with_invalid_idx(idx):
    nb_metadata = NotebookMetadata(
        name="test",
        version="v1.0.0",
        edition=1,
        license="unspecified",
        source_file="",
        private=False,
        metadata={},
        dataset={
            "author": "test",
            "files": [{"url": "file://local/filename.txt", "hash": "myhash"}],
        },
    )

    with pytest.raises(ValueError, match="Requested index does not exist"):
        nb_metadata.download_file(idx)
