import hashlib
import os

import datapackage
import pandas as pd
import pytest
import scmdata.testing
from pandas.testing import assert_frame_equal

from bookshelf.book import LocalBook, validate_dataframe_structure
from bookshelf.constants import DATA_FORMAT_VERSION, TEST_DATA_DIR
from bookshelf.shelf import BookShelf


def test_book_info():
    book = LocalBook("missing", "v1.1.0")
    assert book.name == "missing"
    assert book.version == "v1.1.0"


def test_book_without_metadata():
    book = LocalBook("missing", "v1.0.0")
    with pytest.raises(FileNotFoundError):
        book.metadata()


def test_create_local(local_bookshelf):
    expected_fname = local_bookshelf / "test" / "v1.0.0_e001" / "datapackage.json"

    assert not expected_fname.exists()
    LocalBook.create_new("test", "v1.0.0", local_bookshelf=local_bookshelf)
    assert expected_fname.exists()


def test_add_timeseries(local_bookshelf, example_data, example_long_format_data):
    book = LocalBook.create_new("test", "v1.1.0", local_bookshelf=local_bookshelf)
    book.add_timeseries("test", example_data)
    assert len(book.as_datapackage().resources) == 2
    expected_fname = local_bookshelf / "test" / "v1.1.0_e001" / "test_v1.1.0_e001_test_wide.csv.gz"
    assert expected_fname.exists()

    res = book.as_datapackage().resources[0]
    assert res.name == "test_wide"
    assert res.descriptor["timeseries_name"] == "test"
    assert res.descriptor["shape"] == "wide"
    assert res.descriptor["format"] == "csv.gz"
    assert res.descriptor["filename"] == "test_v1.1.0_e001_test_wide.csv.gz"
    timeseries_data = pd.DataFrame(example_data.timeseries().sort_index())
    content_hash = hashlib.sha256(timeseries_data.to_csv().encode()).hexdigest()
    assert res.descriptor["content_hash"] == content_hash

    expected_fname = local_bookshelf / "test" / "v1.1.0_e001" / "test_v1.1.0_e001_test_long.csv.gz"
    assert expected_fname.exists()

    res = book.as_datapackage().resources[1]
    assert res.name == "test_long"
    assert res.descriptor["timeseries_name"] == "test"
    assert res.descriptor["shape"] == "long"
    assert res.descriptor["format"] == "csv.gz"
    assert res.descriptor["filename"] == "test_v1.1.0_e001_test_long.csv.gz"
    content_hash = hashlib.sha256(example_long_format_data.to_csv().encode()).hexdigest()
    assert res.descriptor["content_hash"] == content_hash


def test_add_wide_timeseries(local_bookshelf, example_unsorted_data, example_data):
    book = LocalBook.create_new("test_unsorted", "v1.1.0", local_bookshelf=local_bookshelf)
    book.write_wide_timeseries(example_unsorted_data, "test", {"format": "csv.gz", "compression": "gzip"})
    assert len(book.as_datapackage().resources) == 1

    expected_fname = (
        local_bookshelf / "test_unsorted" / "v1.1.0_e001" / "test_unsorted_v1.1.0_e001_test_wide.csv.gz"
    )
    assert expected_fname.exists()

    res = book.as_datapackage().resources[0]
    timeseries_data = pd.DataFrame(example_data.timeseries().sort_index())
    content_hash = hashlib.sha256(timeseries_data.to_csv().encode()).hexdigest()
    assert res.descriptor["content_hash"] == content_hash


def test_add_long_timeseries(local_bookshelf, example_unsorted_data, example_long_format_data):
    book = LocalBook.create_new("test_unsorted", "v1.1.0", local_bookshelf=local_bookshelf)
    book.write_long_timeseries(example_unsorted_data, "test", {"format": "csv.gz", "compression": "gzip"})
    assert len(book.as_datapackage().resources) == 1

    expected_fname = (
        local_bookshelf / "test_unsorted" / "v1.1.0_e001" / "test_unsorted_v1.1.0_e001_test_long.csv.gz"
    )
    assert expected_fname.exists()

    res = book.as_datapackage().resources[0]
    content_hash = hashlib.sha256(example_long_format_data.to_csv().encode()).hexdigest()
    assert res.descriptor["content_hash"] == content_hash


def test_timeseries(example_data):
    book = LocalBook.create_new("test", "v1.1.0")
    book.add_timeseries("test", example_data)
    scmdata.testing.assert_scmdf_almost_equal(example_data, book.timeseries("test"))

    with pytest.raises(ValueError, match="Unknown timeseries 'other_wide'"):
        book.timeseries("other")


def test_get_long_format_data(example_data, example_long_format_data):
    book = LocalBook.create_new("test", "v1.1.0")
    book.add_timeseries("test", example_data)
    assert_frame_equal(example_long_format_data, book.get_long_format_data("test"))

    with pytest.raises(ValueError, match="Unknown timeseries 'other_long'"):
        book.get_long_format_data("other")


def test_timeseries_remote(example_data, remote_bookshelf):
    book = BookShelf().load("test", "v1.0.0")
    scmdata.testing.assert_scmdf_almost_equal(example_data, book.timeseries("leakage_rates_low"))
    with pytest.raises(ValueError, match="Unknown timeseries 'other_wide'"):
        book.timeseries("other")


def test_metadata():
    book = LocalBook(
        "example",
        "v1.0.0",
        local_bookshelf=os.path.join(TEST_DATA_DIR, DATA_FORMAT_VERSION),
    )
    package = book.as_datapackage()

    assert isinstance(package, datapackage.Package)

    meta_dict = package.descriptor
    assert meta_dict["name"] == book.name
    assert meta_dict["version"] == book.version

    assert meta_dict == book.metadata()


def test_metadata_missing():
    book = LocalBook("example", "v1.0.0")

    with pytest.raises(FileNotFoundError):
        book.metadata()


def test_files(local_bookshelf):
    book = LocalBook("example", "v1.0.0")

    assert len(book.files()) == 0

    book = LocalBook(
        "example",
        "v1.0.0",
        local_bookshelf=os.path.join(TEST_DATA_DIR, DATA_FORMAT_VERSION),
    )
    assert len(book.files()) == 4

    book = LocalBook.create_new("example", "v1.1.0", local_bookshelf=local_bookshelf)
    book_files = book.files()
    assert len(book_files) == 1
    assert book_files[0] == os.path.join(book.local_fname("datapackage.json"))


def test_validate_dataframe_structure_valid():
    """Test validate_dataframe_structure with valid DataFrame."""
    df = pd.DataFrame(
        {
            "country": ["USA", "CHN", "IND"],
            "population": [331_000_000, 1_412_000_000, 1_380_000_000],
            "gdp_per_capita": [65_280.0, 10_500.0, 1_900.0],
            "is_developed": [True, False, False],
        }
    )

    result = validate_dataframe_structure(df)

    # Should return a DataFrame
    assert isinstance(result, pd.DataFrame)

    # Should have the same columns
    assert list(result.columns) == ["country", "population", "gdp_per_capita", "is_developed"]

    # Should have the same data
    assert_frame_equal(result, df.reset_index(drop=True))

    # Should have reset index (unnamed index dropped)
    assert result.index.name is None
    assert list(result.index) == [0, 1, 2]


def test_validate_dataframe_structure_rejects_multiindex_columns():
    """Test validate_dataframe_structure rejects DataFrame with MultiIndex columns."""
    # Create DataFrame with MultiIndex columns
    arrays = [
        ["metric", "metric", "info", "info"],
        ["population", "gdp", "name", "region"],
    ]
    columns = pd.MultiIndex.from_arrays(arrays, names=["category", "field"])
    df = pd.DataFrame(
        [[331_000_000, 65_280.0, "USA", "North America"]],
        columns=columns,
    )

    # Should raise ValueError for MultiIndex columns
    with pytest.raises(ValueError, match="DataFrame cannot have MultiIndex columns"):
        validate_dataframe_structure(df)


def test_validate_dataframe_structure_rejects_multiindex_index():
    """Test validate_dataframe_structure rejects DataFrame with MultiIndex index."""
    # Create DataFrame with MultiIndex index
    index = pd.MultiIndex.from_tuples(
        [("USA", 2020), ("USA", 2021), ("CHN", 2020)],
        names=["country", "year"],
    )
    df = pd.DataFrame(
        {"population": [331_000_000, 332_000_000, 1_412_000_000]},
        index=index,
    )

    # Should raise ValueError for MultiIndex index
    with pytest.raises(ValueError, match="DataFrame cannot have MultiIndex index"):
        validate_dataframe_structure(df)


def test_validate_dataframe_structure_rejects_unsupported_dtypes():
    """Test validate_dataframe_structure rejects DataFrame with unsupported dtypes."""
    # Create DataFrame with complex dtype (not in supported list)
    df = pd.DataFrame(
        {
            "name": ["USA", "China", "India"],
            "population": [331_000_000, 1_412_000_000, 1_380_000_000],
            "complex_value": [1 + 2j, 3 + 4j, 5 + 6j],  # Complex numbers have dtype.kind='c'
        }
    )

    # Should raise ValueError for unsupported dtype
    with pytest.raises(
        ValueError,
        match=(
            r"DataFrame contains unsupported dtypes.*'complex_value'.*complex.*"
            r"Supported types are: int, float, str, bool, datetime, timedelta"
        ),
    ):
        validate_dataframe_structure(df)


def test_validate_dataframe_structure_rejects_object_with_non_strings():
    """Test validate_dataframe_structure rejects object dtype columns containing non-string values."""
    # Create DataFrame with object column containing lists (not strings)
    df = pd.DataFrame(
        {
            "name": ["USA", "China", "India"],
            "tags": [["large", "developed"], ["large"], ["developing"]],  # Lists, not strings
        }
    )

    with pytest.raises(
        ValueError,
        match=(
            r"DataFrame contains unsupported dtypes.*'tags'.*object \(list\).*"
            r"Supported types are: int, float, str, bool, datetime, timedelta"
        ),
    ):
        validate_dataframe_structure(df)


def test_add_dataframe(local_bookshelf):
    """Test adding a DataFrame resource to a Book."""
    # Create a test DataFrame
    df = pd.DataFrame(
        {
            "country": ["USA", "China", "India"],
            "region": ["North America", "Asia", "Asia"],
            "population": [331_000_000, 1_412_000_000, 1_380_000_000],
            "gdp_per_capita": [65_280.0, 10_500.0, 1_900.0],
            "is_developed": [True, False, False],
        }
    )

    # Create a new book and add the dataframe
    book = LocalBook.create_new("test_df", "v1.0.0", local_bookshelf=local_bookshelf)
    book.add_dataframe("country_info", df, compressed=True)

    # Check that the resource was added to the datapackage
    package = book.as_datapackage()
    assert len(package.resources) == 1

    # Check resource metadata
    resource = package.resources[0]
    assert resource.name == "dataframe_country_info"
    assert resource.descriptor["dataframe_name"] == "country_info"
    assert resource.descriptor["resource_type"] == "dataframe"
    assert resource.descriptor["format"] == "parquet.gz"
    assert resource.descriptor["filename"] == "test_df_v1.0.0_e001_country_info.parquet.gz"
    assert resource.descriptor["columns"] == [
        "country",
        "region",
        "population",
        "gdp_per_capita",
        "is_developed",
    ]
    assert "hash" in resource.descriptor
    assert "content_hash" in resource.descriptor

    # Check that the file was created
    expected_fname = (
        local_bookshelf / "test_df" / "v1.0.0_e001" / "test_df_v1.0.0_e001_country_info.parquet.gz"
    )
    assert expected_fname.exists()


def test_add_dataframe_uncompressed(local_bookshelf):
    """Test adding an uncompressed DataFrame resource to a Book."""
    df = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "value": [10.5, 20.3, 30.1],
        }
    )

    book = LocalBook.create_new("test_df_uncompressed", "v2.0.0", local_bookshelf=local_bookshelf)
    book.add_dataframe("data", df, compressed=False)

    # Check resource metadata
    resource = book.as_datapackage().resources[0]
    assert resource.descriptor["format"] == "parquet"
    assert resource.descriptor["filename"] == "test_df_uncompressed_v2.0.0_e001_data.parquet"

    # Check that the file was created
    expected_fname = (
        local_bookshelf
        / "test_df_uncompressed"
        / "v2.0.0_e001"
        / "test_df_uncompressed_v2.0.0_e001_data.parquet"
    )
    assert expected_fname.exists()


def test_add_dataframe_with_named_index(local_bookshelf):
    """Test adding a DataFrame with a named index - should preserve index as a column."""
    df = pd.DataFrame(
        {
            "population": [331_000_000, 1_412_000_000, 1_380_000_000],
            "gdp": [65_280.0, 10_500.0, 1_900.0],
        },
        index=pd.Index(["USA", "CHN", "IND"], name="country_code"),
    )

    book = LocalBook.create_new("test_df_indexed", "v1.0.0", local_bookshelf=local_bookshelf)
    book.add_dataframe("economics", df, compressed=True)

    # Retrieve the dataframe and check that index became a column
    retrieved_df = book.dataframe("economics")

    # Should have 3 columns: country_code (from index), population, gdp
    assert list(retrieved_df.columns) == ["country_code", "population", "gdp"]
    assert retrieved_df["country_code"].tolist() == ["USA", "CHN", "IND"]
    assert retrieved_df["population"].tolist() == [331_000_000, 1_412_000_000, 1_380_000_000]


def test_dataframe_retrieval(local_bookshelf):
    """Test retrieving a DataFrame resource from a Book."""
    # Create and populate book
    df_original = pd.DataFrame(
        {
            "country": ["USA", "China", "India"],
            "region": ["North America", "Asia", "Asia"],
            "population": [331_000_000, 1_412_000_000, 1_380_000_000],
        }
    )

    book = LocalBook.create_new("test_retrieval", "v1.0.0", local_bookshelf=local_bookshelf)
    book.add_dataframe("countries", df_original, compressed=True)

    # Retrieve the dataframe
    df_retrieved = book.dataframe("countries")

    # Check that data matches
    assert_frame_equal(df_retrieved, df_original)


def test_dataframe_unknown_resource(local_bookshelf):
    """Test that retrieving an unknown DataFrame resource raises ValueError."""
    book = LocalBook.create_new("test_unknown", "v1.0.0", local_bookshelf=local_bookshelf)

    with pytest.raises(ValueError, match="Unknown dataframe 'dataframe_nonexistent'"):
        book.dataframe("nonexistent")


def test_dataframe_remote(remote_bookshelf):
    """Test retrieving a DataFrame resource from a remote BookShelf."""
    # Load the example_with_dataframe book from the remote bookshelf
    book = BookShelf().load("example_with_dataframe", "v1.0.0")

    # Retrieve the dataframe
    df = book.dataframe("country_metadata")

    # Check the structure
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["iso_code", "name", "region", "population", "gdp_per_capita"]
    assert len(df) > 0

    # Check that the data is reasonable (basic sanity check)
    assert df["population"].dtype in [int, "int64", "Int64"]
    assert df["gdp_per_capita"].dtype in [float, "float64"]


def test_add_dataframe_with_datetime(local_bookshelf):
    """Test adding a DataFrame with datetime columns."""
    df = pd.DataFrame(
        {
            "event": ["Event A", "Event B", "Event C"],
            "timestamp": pd.to_datetime(["2020-01-01", "2021-06-15", "2023-12-31"]),
            "duration": pd.to_timedelta(["1 days", "2 hours", "30 minutes"]),
        }
    )

    book = LocalBook.create_new("test_datetime", "v1.0.0", local_bookshelf=local_bookshelf)
    book.add_dataframe("events", df, compressed=True)

    # Retrieve and verify
    df_retrieved = book.dataframe("events")
    assert list(df_retrieved.columns) == ["event", "timestamp", "duration"]
    assert df_retrieved["timestamp"].dtype == "datetime64[ns]" or pd.api.types.is_datetime64_any_dtype(
        df_retrieved["timestamp"]
    )
    assert df_retrieved["duration"].dtype == "timedelta64[ns]" or pd.api.types.is_timedelta64_dtype(
        df_retrieved["duration"]
    )
