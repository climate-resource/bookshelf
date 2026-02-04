"""Authentication commands for bookshelf CLI."""

from datetime import datetime, timezone

import click
from rich.console import Console
from rich.table import Table

from bookshelf.api.client import BookshelfAPIClient
from bookshelf.api.errors import AuthenticationError
from bookshelf.auth import (
    clear_credentials,
    get_api_url,
    get_credentials_path,
    is_authenticated,
    load_credentials,
    save_credentials,
)

console = Console()


@click.group(name="auth")
def auth_group() -> None:
    """Manage authentication for the bookshelf API."""
    pass


@auth_group.command(name="login")
@click.option("--username", prompt=True, help="Username or email")
@click.option("--password", prompt=True, hide_input=True, help="Password")
@click.option(
    "--api-url",
    envvar="BOOKSHELF_API_URL",
    help="API base URL (default: from environment or https://bookshelf.climate-resource.com/api)",
)
def login(username: str, password: str, api_url: str | None) -> None:
    """Login to the bookshelf API and store credentials."""
    # Use provided URL or fall back to default
    base_url = api_url or get_api_url()

    console.print(f"[cyan]Authenticating with {base_url}...[/cyan]")

    try:
        # Create API client and authenticate
        client = BookshelfAPIClient(base_url=base_url)
        token_response = client.authenticate(username, password)

        # Save credentials
        save_credentials(
            access_token=token_response.access_token,
            token_type=token_response.token_type,
            expires_in=token_response.expires_in,
            api_url=base_url,
        )

        console.print("[green]✓[/green] Login successful!")
        console.print(f"[dim]Token expires in {token_response.expires_in} seconds[/dim]")
        console.print(f"[dim]Credentials saved to {get_credentials_path()}[/dim]")

    except AuthenticationError as e:
        console.print(f"[red]✗[/red] Authentication failed: {e.message}")
        raise click.Abort()
    except Exception as e:
        console.print(f"[red]✗[/red] Login failed: {e!s}")
        raise click.Abort()


@auth_group.command(name="logout")
def logout() -> None:
    """Clear stored credentials."""
    if not is_authenticated():
        console.print("[yellow]⚠[/yellow] Not currently logged in.")
        return

    clear_credentials()
    console.print("[green]✓[/green] Logged out successfully.")
    console.print(f"[dim]Credentials removed from {get_credentials_path()}[/dim]")


@auth_group.command(name="status")
def status() -> None:
    """Show current authentication status."""
    # Create a table for status information
    table = Table(title="Authentication Status", show_header=False, box=None)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    if is_authenticated():
        creds = load_credentials()
        if creds:
            table.add_row("Status", "[green]Logged in[/green]")
            table.add_row("API URL", creds["api_url"])
            table.add_row("Token Type", creds["token_type"])

            # Show expiry information
            if creds["expires_at"]:
                expires_at = creds["expires_at"]
                now = datetime.now(timezone.utc)
                time_left = expires_at - now

                if time_left.total_seconds() > 0:
                    hours = int(time_left.total_seconds() // 3600)
                    minutes = int((time_left.total_seconds() % 3600) // 60)
                    table.add_row(
                        "Token Expires",
                        f"{expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')} ({hours}h {minutes}m remaining)",
                    )
                else:
                    table.add_row("Token Expires", "[red]EXPIRED[/red]")
            else:
                table.add_row("Token Expires", "Never")

            table.add_row("Credentials File", str(get_credentials_path()))
        else:
            table.add_row("Status", "[yellow]Unknown (invalid credentials)[/yellow]")
    else:
        table.add_row("Status", "[red]Not logged in[/red]")
        table.add_row("Credentials File", str(get_credentials_path()))

    console.print(table)

    # Show help if not authenticated
    if not is_authenticated():
        console.print("\n[dim]Run 'bookshelf-client auth login' to authenticate[/dim]")
