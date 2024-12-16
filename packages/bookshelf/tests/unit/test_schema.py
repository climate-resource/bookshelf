import os

import pytest
from pydantic.v1 import ValidationError

from bookshelf.schema import DatasetMetadata, NotebookMetadata
from bookshelf.utils import get_notebook_directory


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
                "allowed_NA": False,
                "required_column": True,
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
                "allowed_NA": False,
                "required_column": True,
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
                "allowed_NA": False,
                "required_column": True,
            }
        ],
    )

    data_dictionary_dict = notebook_metadata_no_cv.data_dictionary

    assert data_dictionary_dict == notebook.data_dictionary


def test_notebook_metadata_invalid_data_dictionary():
    with pytest.raises(ValidationError) as exc_info:
        NotebookMetadata(
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
                    # 'description' field is missing here
                    "type": "string",
                    "allowed_NA": False,
                    "required_column": True,
                }
            ],
        )

    error = exc_info.value

    assert any(
        "description" in e["loc"] for e in error.errors()
    ), "ValidationError should be for missing 'description'"


@pytest.mark.parametrize("idx", (None, 0, -1))
def test_download_files(idx, notebook_metadata):
    # doesn't trigger pooch.retrieve
    # TODO: add tests for pooch functionality

    if idx:
        res = notebook_metadata.download_file(idx)
    else:
        res = notebook_metadata.download_file()

    assert res == os.path.join(get_notebook_directory(), "local/filename.txt")


@pytest.mark.parametrize("idx", (-100, 999))
def test_download_files_with_invalid_idx(idx, notebook_metadata):
    with pytest.raises(ValueError, match="Requested index does not exist"):
        notebook_metadata.download_file(idx)
