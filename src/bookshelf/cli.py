import os

import click

cmd_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "commands"))


class CLICommands(click.MultiCommand):
    def list_commands(self, ctx):
        rv = []
        for filename in os.listdir(cmd_folder):
            if filename.endswith(".py") and filename.startswith("cmd_"):
                rv.append(filename[4:-3])
        rv.sort()
        return rv

    def get_command(self, ctx, name):
        try:
            mod = __import__(f"bookshelf.commands.cmd_{name}", None, None, ["cli"])
        except ImportError:
            return  # pragma: no cover
        return mod.cli


@click.command(cls=CLICommands, name="bookshelf")
def main():
    """
    Bookshelf for managing reusable datasets
    """
