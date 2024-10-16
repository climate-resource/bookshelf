"""
Constants
"""

import os

DATA_FORMAT_VERSION = "v0.3.2"
"""
Version of the data format

This follows the semantic versioning scheme.
"""
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

DATA_DIR = os.path.join(ROOT_DIR, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
TEST_DATA_DIR = os.path.join(ROOT_DIR, "tests", "test-data")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed", DATA_FORMAT_VERSION)


DEFAULT_BOOKSHELF = f"https://cr-prod-datasets-bookshelf.s3.us-west-2.amazonaws.com/{DATA_FORMAT_VERSION}"
"""Default URL for the remote bookshelf"""
ENV_PREFIX = "BOOKSHELF_"
"""Prefix for environment variables"""
