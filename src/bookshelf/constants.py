import os


DATA_FORMAT_VERSION = "v0.1.0"
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

DATA_DIR = os.path.join(ROOT_DIR, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
TEST_DATA_DIR = os.path.join(ROOT_DIR, "tests", "test-data")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed", DATA_FORMAT_VERSION)


DEFAULT_BOOKSHELF = f"https://bookshelf.local/{DATA_FORMAT_VERSION}"
