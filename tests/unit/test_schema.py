import pytest

from bookshelf.schema import DatasetMetadata, NotebookMetadata


@pytest.fixture
def notebook_metadata():
    return NotebookMetadata(
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
        data_dictionary=[
            {
                "name": "test",
                "description": "test description",
                "type": "string",
                "required": True,
                "controlled_vocabulary": [{"value": "test", "description": "test description"}],
            }
        ],
    )


def test_file():
    res = DatasetMetadata(author="test")
    assert res.files == []


@pytest.fixture
def notebook_metadata_no_cv():
    return NotebookMetadata(
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
        data_dictionary=[
            {
                "name": "test",
                "description": "test description",
                "type": "string",
                "required": True,
            }
        ],
    )


def test_notebook_metadata_no_controlled_vocabulary(notebook_metadata_no_cv):
    notebook = NotebookMetadata(
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
        data_dictionary=[
            {
                "name": "test",
                "description": "test description",
                "type": "string",
                "required": True,
            }
        ],
    )

    data_dictionary_dict = notebook_metadata_no_cv.data_dictionary

    assert data_dictionary_dict == notebook.data_dictionary


@pytest.mark.parametrize("idx", (None, 0, -1))
def test_download_files(idx, notebook_metadata):
    # doesn't trigger pooch.retrieve
    # TODO: add tests for pooch functionality

    if idx:
        res = notebook_metadata.download_file(idx)
    else:
        res = notebook_metadata.download_file()

    assert res == "local/filename.txt"


@pytest.mark.parametrize("idx", (-100, 999))
def test_download_files_with_invalid_idx(idx, notebook_metadata):
    with pytest.raises(ValueError, match="Requested index does not exist"):
        notebook_metadata.download_file(idx)
