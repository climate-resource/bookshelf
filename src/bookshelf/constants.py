"""
Constants
"""
import os

DATA_FORMAT_VERSION = "v0.2.1"
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

DATA_DIR = os.path.join(ROOT_DIR, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
TEST_DATA_DIR = os.path.join(ROOT_DIR, "tests", "test-data")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed", DATA_FORMAT_VERSION)


DEFAULT_BOOKSHELF = (
    "https://cr-prod-datasets-bookshelf.s3.us-west-2.amazonaws.com" f"/{DATA_FORMAT_VERSION}"
)
ENV_PREFIX = "BOOKSHELF_"
