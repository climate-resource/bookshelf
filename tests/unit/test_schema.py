from bookshelf.schema import DatasetMetadata


def test_file():
    res = DatasetMetadata(author="test")
    assert res.files == []
