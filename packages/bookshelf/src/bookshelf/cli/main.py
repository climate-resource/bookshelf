"""Main CLI entry point for bookshelf-client."""

import click

from bookshelf.cli.commands import auth, books, volumes


@click.group(name="bookshelf-client")
@click.version_option()
def main() -> None:
    """
    Bookshelf Client - CLI for interacting with the bookshelf-platform API.

    Use 'bsc' as a short alias for 'bookshelf-client'.
    """
    pass


# Register command groups
main.add_command(auth.auth_group)
main.add_command(volumes.volumes_group)
main.add_command(books.books_group)


if __name__ == "__main__":
    main()
