"""Volume commands for bookshelf CLI."""

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from bookshelf.api.client import BookshelfAPIClient
from bookshelf.api.errors import APIError, AuthenticationError, NotFoundError
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
        return f"{size_bytes / _KB:.2f} KB"
    elif size_bytes < _GB:
        return f"{size_bytes / _MB:.2f} MB"
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


@click.group(name="volumes")
def volumes_group() -> None:
    """Volume management commands."""
    pass


@volumes_group.command(name="list")
@click.option("--limit", default=100, help="Maximum number of volumes to return (1-1000)")
@click.option("--offset", default=0, help="Number of volumes to skip")
def list_volumes(limit: int, offset: int) -> None:
    """List all available volumes."""
    try:
        client = get_authenticated_client()

        with console.status("[cyan]Fetching volumes...[/cyan]"):
            response = client.list_volumes(limit=limit, offset=offset)

        if not response.items:
            console.print("[yellow]No volumes found.[/yellow]")
            return

        # Create a table for volumes
        table = Table(title=f"Volumes (showing {len(response.items)} of {response.total})")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Description", style="white", overflow="fold")
        table.add_column("License", style="yellow")
        table.add_column("Latest Version", style="green")
        table.add_column("Resource Types", style="magenta")

        for volume in response.items:
            resource_types = ", ".join(volume.resource_types) if volume.resource_types else "-"
            latest = f"{volume.latest_version}" if volume.latest_version else "-"
            if volume.latest_edition:
                latest += f"_e{volume.latest_edition:03}"

            table.add_row(
                volume.name,
                volume.description or "-",
                volume.license,
                latest,
                resource_types,
            )

        console.print(table)

        # Show pagination info
        if response.has_more:
            start = offset + 1
            end = offset + len(response.items)
            console.print(f"\n[dim]Showing {start}-{end} of {response.total} volumes[/dim]")
            console.print(f"[dim]Use --offset {offset + limit} to see more[/dim]")

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


@volumes_group.command(name="show")
@click.argument("name")
def show_volume(name: str) -> None:  # noqa: PLR0915
    """Show detailed information about a volume."""
    try:
        client = get_authenticated_client()

        with console.status(f"[cyan]Fetching volume '{name}'...[/cyan]"):
            volume = client.get_volume(name)

        # Display volume metadata in a panel
        info_table = Table(show_header=False, box=None, padding=(0, 2))
        info_table.add_column("Key", style="cyan", no_wrap=True)
        info_table.add_column("Value", style="white")

        info_table.add_row("Name", volume.name)
        info_table.add_row("Description", volume.description or "-")
        info_table.add_row("License", volume.license)
        info_table.add_row("Created", volume.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
        info_table.add_row("Updated", volume.updated_at.strftime("%Y-%m-%d %H:%M:%S UTC"))

        console.print(Panel(info_table, title=f"Volume: {name}", border_style="cyan"))

        # Display statistics
        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Metric", style="cyan", no_wrap=True)
        stats_table.add_column("Value", style="green")

        stats_table.add_row("Total Versions", str(volume.stats.total_versions))
        stats_table.add_row("Total Editions", str(volume.stats.total_editions))
        stats_table.add_row("Total Resources", str(volume.stats.total_resources))

        stats_table.add_row("Total Size", _format_size(volume.stats.total_size_bytes))

        console.print(Panel(stats_table, title="Statistics", border_style="green"))

        # Display versions
        if volume.versions:
            versions_table = Table(title="Versions")
            versions_table.add_column("Version", style="cyan")
            versions_table.add_column("Editions", style="yellow")
            versions_table.add_column("Status", style="white")

            for version_info in volume.versions:
                editions_str = ", ".join([f"e{ed.edition:03}" for ed in version_info.editions])
                statuses = set(ed.status for ed in version_info.editions)
                status_str = ", ".join(statuses)

                versions_table.add_row(
                    version_info.version,
                    editions_str,
                    status_str,
                )

            console.print(versions_table)
        else:
            console.print("[yellow]No versions available.[/yellow]")

        # Display metadata if present
        if volume.metadata:
            console.print("\n[bold cyan]Metadata:[/bold cyan]")
            for key, value in volume.metadata.items():
                console.print(f"  [cyan]{key}:[/cyan] {value}")

    except NotFoundError:
        console.print(f"[red]✗[/red] Volume '{name}' not found.")
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
