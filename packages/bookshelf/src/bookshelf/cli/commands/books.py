"""Book commands for bookshelf CLI."""

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from bookshelf.api.client import BookshelfAPIClient
from bookshelf.api.errors import APIError, AuthenticationError, NotFoundError
from bookshelf.api.schemas import BookResponse, BookStatus
from bookshelf.auth import get_api_url, get_token

console = Console()

# Size constants for human-readable formatting
_KB = 1024
_MB = _KB * 1024
_GB = _MB * 1024


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if size_bytes < _KB:
        return f"{size_bytes} B"
    elif size_bytes < _MB:
        return f"{size_bytes / _KB:.1f} KB"
    elif size_bytes < _GB:
        return f"{size_bytes / _MB:.1f} MB"
    else:
        return f"{size_bytes / _GB:.2f} GB"


def get_authenticated_client() -> BookshelfAPIClient:
    """Get an authenticated API client or raise an error."""
    token = get_token()
    if not token:
        console.print("[red]✗[/red] Not authenticated. Please run 'bookshelf-client auth login' first.")
        raise click.Abort()

    api_url = get_api_url()
    return BookshelfAPIClient(base_url=api_url, token=token)


@click.group(name="books")
def books_group() -> None:
    """Book management commands."""
    pass


@books_group.command(name="list")
@click.argument("volume")
@click.option("--version", help="Filter by version")
@click.option(
    "--status",
    type=click.Choice(["draft", "published"], case_sensitive=False),
    help="Filter by status",
)
@click.option("--latest-only", is_flag=True, help="Show only the latest edition per version")
@click.option("--limit", default=100, help="Maximum number of books to return (1-1000)")
@click.option("--offset", default=0, help="Number of books to skip")
def list_books(  # noqa: PLR0913
    volume: str,
    version: str | None,
    status: str | None,
    latest_only: bool,
    limit: int,
    offset: int,
) -> None:
    """List books in a volume."""
    try:
        client = get_authenticated_client()

        # Convert status string to enum if provided
        status_enum = None
        if status:
            status_enum = BookStatus.DRAFT if status.lower() == "draft" else BookStatus.PUBLISHED

        with console.status(f"[cyan]Fetching books from volume '{volume}'...[/cyan]"):
            response = client.list_books(
                volume_name=volume,
                version=version,
                status=status_enum,
                latest_only=latest_only,
                limit=limit,
                offset=offset,
            )

        if not response.items:
            console.print(f"[yellow]No books found in volume '{volume}'.[/yellow]")
            return

        # Create a table for books
        title = f"Books in '{volume}'"
        if version:
            title += f" (version {version})"
        if status:
            title += f" [{status}]"
        title += f" (showing {len(response.items)} of {response.total})"

        table = Table(title=title)
        table.add_column("Version", style="cyan", no_wrap=True)
        table.add_column("Edition", style="yellow", no_wrap=True)
        table.add_column("Status", style="white")
        table.add_column("Resources", style="magenta", justify="right")
        table.add_column("Published", style="green")
        table.add_column("Created", style="dim")

        for book in response.items:
            status_color = "green" if book.status == BookStatus.PUBLISHED else "yellow"
            status_str = f"[{status_color}]{book.status.value}[/{status_color}]"

            published_str = book.published_at.strftime("%Y-%m-%d") if book.published_at else "-"

            table.add_row(
                book.version,
                f"e{book.edition:03}",
                status_str,
                str(book.resource_count),
                published_str,
                book.created_at.strftime("%Y-%m-%d"),
            )

        console.print(table)

        # Show pagination info
        if response.has_more:
            console.print(
                f"\n[dim]Showing {offset + 1}-{offset + len(response.items)} of {response.total} books[/dim]"
            )
            console.print(f"[dim]Use --offset {offset + limit} to see more[/dim]")

    except NotFoundError:
        console.print(f"[red]✗[/red] Volume '{volume}' not found.")
        raise click.Abort()
    except AuthenticationError as e:
        console.print(f"[red]✗[/red] Authentication failed: {e.message}")
        console.print("[dim]Your token may have expired. Try 'bookshelf-client auth login'[/dim]")
        raise click.Abort()
    except APIError as e:
        console.print(f"[red]✗[/red] API error: {e.message}")
        raise click.Abort()
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e!s}")
        raise click.Abort()


def _display_book_info(book: BookResponse, volume: str) -> None:
    """Display book metadata in a panel."""
    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("Key", style="cyan", no_wrap=True)
    info_table.add_column("Value", style="white")

    info_table.add_row("Volume", book.volume_id)
    info_table.add_row("Version", book.version)
    info_table.add_row("Edition", f"e{book.edition:03}")
    info_table.add_row("Full Version", f"{book.version}_e{book.edition:03}")

    status_color = "green" if book.status == BookStatus.PUBLISHED else "yellow"
    info_table.add_row("Status", f"[{status_color}]{book.status.value}[/{status_color}]")
    info_table.add_row("Private", "Yes" if book.private else "No")

    if book.description:
        info_table.add_row("Description", book.description)

    info_table.add_row("Created", book.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
    info_table.add_row("Updated", book.updated_at.strftime("%Y-%m-%d %H:%M:%S UTC"))

    if book.published_at:
        info_table.add_row("Published", book.published_at.strftime("%Y-%m-%d %H:%M:%S UTC"))

    if book.hash:
        info_table.add_row("Hash", book.hash[:16] + "...")

    console.print(Panel(info_table, title=f"Book: {volume}@{book.version}", border_style="cyan"))


def _display_book_resources(book: BookResponse) -> None:
    """Display book resources in a table."""
    if not book.resources:
        console.print("[yellow]No resources in this book.[/yellow]")
        return

    resources_table = Table(title="Resources")
    resources_table.add_column("Name", style="cyan")
    resources_table.add_column("Type", style="yellow")
    resources_table.add_column("Format", style="magenta")
    resources_table.add_column("Size", style="green", justify="right")

    for resource in book.resources:
        resources_table.add_row(
            resource.name,
            resource.type,
            resource.format,
            _format_size(resource.size_bytes),
        )

    console.print(resources_table)


def _display_book_data_dictionary(book: BookResponse) -> None:
    """Display book data dictionary in a table."""
    if not book.data_dictionary:
        return

    dict_table = Table(title="Data Dictionary")
    dict_table.add_column("Field", style="cyan")
    dict_table.add_column("Type", style="yellow")
    dict_table.add_column("Description", style="white")
    dict_table.add_column("Unit", style="magenta")
    dict_table.add_column("Required", style="green")

    for entry in book.data_dictionary:
        dict_table.add_row(
            entry.name,
            entry.type,
            entry.description or "-",
            entry.unit or "-",
            "Yes" if entry.required else "No",
        )

    console.print(dict_table)


def _display_book_metadata(book: BookResponse) -> None:
    """Display book metadata."""
    if not book.metadata:
        return

    console.print("\n[bold cyan]Metadata:[/bold cyan]")
    for key, value in book.metadata.items():
        console.print(f"  [cyan]{key}:[/cyan] {value}")


@books_group.command(name="show")
@click.argument("volume")
@click.argument("version")
@click.option("--edition", type=int, help="Specific edition (defaults to latest)")
def show_book(volume: str, version: str, edition: int | None) -> None:
    """Show detailed information about a book."""
    try:
        client = get_authenticated_client()

        edition_str = f"edition {edition}" if edition else "latest edition"
        with console.status(f"[cyan]Fetching book '{volume}' {version} ({edition_str})...[/cyan]"):
            book = client.get_book(volume_name=volume, version=version, edition=edition)

        _display_book_info(book, volume)
        _display_book_resources(book)
        _display_book_data_dictionary(book)
        _display_book_metadata(book)

    except NotFoundError:
        edition_str = f" edition {edition}" if edition else ""
        console.print(f"[red]✗[/red] Book '{volume}' version '{version}'{edition_str} not found.")
        raise click.Abort()
    except AuthenticationError as e:
        console.print(f"[red]✗[/red] Authentication failed: {e.message}")
        console.print("[dim]Your token may have expired. Try 'bookshelf-client auth login'[/dim]")
        raise click.Abort()
    except APIError as e:
        console.print(f"[red]✗[/red] API error: {e.message}")
        raise click.Abort()
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e!s}")
        raise click.Abort()
