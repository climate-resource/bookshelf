"""
Bookshelf CLI
"""
import logging
import os

import click
import click_log

cmd_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "commands"))
logger = logging.getLogger("bookshelf")
click_log.basic_config(logger)


class _CLICommands(click.MultiCommand):
    def list_commands(self, ctx):
        commands = []
        for filename in os.listdir(cmd_folder):
            if filename.endswith(".py") and filename.startswith("cmd_"):
                commands.append(filename[4:-3])
        commands.sort()
        return commands

    def get_command(self, ctx, cmd_name):
        try:
            mod = __import__(f"bookshelf.commands.cmd_{cmd_name}", None, None, ["cli"])
        except ImportError:
            return None  # pragma: no cover
        return mod.cli


@click.command(cls=_CLICommands, name="bookshelf")
@click.option("-q", "--quiet", is_flag=True)
@click_log.simple_verbosity_option(logger)
@click.pass_context
def main(ctx, quiet):
    """
    Bookshelf for managing reusable datasets
    """
    ctx.ensure_object(dict)

    logger.setLevel(logging.INFO)
    if quiet:
        logger.setLevel(logging.ERROR)
