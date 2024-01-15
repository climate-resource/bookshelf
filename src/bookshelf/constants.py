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


DEFAULT_S3_BUCKET = "cr-prod-datasets-bookshelf"
"""The default bucket used to store the raw data files"""
DEFAULT_BOOKSHELF = f"https://{DEFAULT_S3_BUCKET}.s3.us-west-2.amazonaws.com/{DATA_FORMAT_VERSION}"
"""Default URL for the remote bookshelf"""
ENV_PREFIX = "BOOKSHELF_"
