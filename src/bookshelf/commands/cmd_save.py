"""
save CLI command
"""
import tempfile

import click

from bookshelf.notebook import run_notebook
from bookshelf.shelf import BookShelf


@click.command("save", short_help="Upload a book to the bookshelf")
@click.argument("name", required=True)
def cli(name):
    """
    Build and upload a Book to the Bookshelf

    Uploading a Book requires the correct AWS credentials (until an authentication
    scheme is introduced). At Climate Resource we use aws-vault for managing multiple
    sets of AWS credentials. Documentation about the different sources of authentication
    can be found here: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html

    To ensure a reproducible build, the Book is built from a notebook in an isolated
    output directory. There currently isn't any functionality to upload a pre-built Book.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        book = run_notebook(name, output_directory=temp_dir, force=False)

        shelf = BookShelf()
        shelf.save(book)
