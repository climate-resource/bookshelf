"""
Bookshelf CLI
"""
import os

import click

cmd_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "commands"))


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
def main():
    """
    Bookshelf for managing reusable datasets
    """
