"""
run CLI command
"""
import logging

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
    "--include-private/--no-include-private",
    help="Run private versions. These will likely fail if the data is not available locally",
    default=False,
)
@click.option(
    "-f",
    "--force",
    help="Override the existing output if the output directory isn't empty",
    is_flag=True,
)
def cli(name: str, output: str, force: bool, version: tuple[str], include_private: bool) -> None:
    """
    Run a notebook

    This runs one of the notebooks used to generate a Book
    """
    if not len(version):
        all_versions = get_available_versions(name, include_private=include_private)
    else:
        all_versions = version

    for dataset_version in all_versions:
        try:
            run_notebook(name, output_directory=output, force=force, version=dataset_version)
        except Exception as exc:
            logger.error(f"Failed to run {name}: {exc}")  # noqa
            raise click.Abort() from exc
