"""
run CLI command
"""
import logging
from typing import Tuple

import click

from bookshelf.notebook import get_available_versions, run_notebook

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
    "--version",
    multiple=True,
    help="List of versions to run",
    required=False,
)
@click.option(
    "-f",
    "--force",
    help="Override the existing output if the output directory isn't empty",
    is_flag=True,
)
def cli(name: str, output: str, force: bool, version: Tuple[str]) -> None:
    """
    Run a notebook

    This runs one of the notebooks used to generate a Book
    """
    if not version:
        all_versions = get_available_versions(name)
    else:
        all_versions = version

    for dataset_version in all_versions:
        try:
            run_notebook(
                name, output_directory=output, force=force, version=dataset_version
            )
        except Exception as exc:
            logger.error(f"Failed to run {name}: {exc}")
            raise click.Abort() from exc
