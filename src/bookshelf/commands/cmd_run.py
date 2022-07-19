"""
run CLI command
"""
import logging

import click

from bookshelf.notebook import run_notebook

logger = logging.getLogger(__name__)


@click.command("run", short_help="Run a notebook")
@click.argument("name", required=True)
@click.option(
    "-o",
    "--output",
    help="Directory to store the artifacts from running the notebook",
    required=False,
)
@click.option(
    "-f",
    "--force",
    help="Override the existing output if the output directory isn't empty",
    is_flag=True,
)
def cli(name, output, force):
    """
    Run a notebook

    This runs one of the notebooks used to generate a Book
    """
    try:
        run_notebook(name, output_directory=output, force=force)
    except Exception as exc:
        logger.error(str(exc))
        raise click.Abort() from exc
