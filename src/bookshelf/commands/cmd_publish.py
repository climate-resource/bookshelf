"""
publish CLI command
"""
import logging
import tempfile

import click

from bookshelf.notebook import get_available_versions, run_notebook
from bookshelf.shelf import BookShelf

logger = logging.getLogger(__name__)


@click.command("publish", short_help="Upload a book to the bookshelf")
@click.argument("name", required=True)
@click.option(
    "--version",
    multiple=True,
    help="List of versions to run",
    required=False,
)
def cli(name, version):
    """
    Build and upload a Book to the Bookshelf

    Uploading a Book requires the correct AWS credentials (until an authentication
    scheme is introduced). At Climate Resource we use aws-vault for managing multiple
    sets of AWS credentials. Documentation about the different sources of authentication
    can be found here: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html

    To ensure a reproducible build, the Book is built from a notebook in an isolated
    output directory. There currently isn't any functionality to upload a pre-built Book.
    """
    if not version:
        all_versions = get_available_versions(name)
    else:
        all_versions = version

    for dataset_version in all_versions:
        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"Building Book in isolated environment: {temp_dir}")
            try:
                book = run_notebook(
                    name,
                    output_directory=temp_dir,
                    force=False,
                    version=dataset_version,
                )
                logger.info(f"Finish building {name}@{book.long_version()}")

                shelf = BookShelf()
                shelf.publish(book)
            except Exception as exc:
                logger.error(str(exc))
                raise click.Abort() from exc
