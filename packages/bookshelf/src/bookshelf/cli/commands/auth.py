"""Authentication commands for bookshelf CLI."""

from datetime import datetime, timezone

import click
from rich.console import Console
from rich.table import Table

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
@click.option(
    "--device-code",
    is_flag=True,
    default=False,
    help="Use device code flow (for headless/SSH environments)",
)
@click.option(
    "--api-url",
    envvar="BOOKSHELF_API_URL",
    help="API base URL (default: from environment or stored credentials)",
)
def login(device_code: bool, api_url: str | None) -> None:
    """Login to the bookshelf API via WorkOS OAuth."""
    from bookshelf.oauth import (
        OAuthError,
        authorization_code_flow,
        poll_device_flow,
        start_device_flow,
    )

    # Use provided URL or fall back to default
    base_url = api_url or get_api_url()

    try:
        if device_code:
            _login_device_code(base_url, start_device_flow, poll_device_flow)
        else:
            _login_pkce(base_url, authorization_code_flow)
    except OAuthError as e:
        console.print(f"[red]x[/red] Authentication failed: {e}")
        raise click.Abort()
    except Exception as e:
        console.print(f"[red]x[/red] Login failed: {e!s}")
        raise click.Abort()


def _login_pkce(base_url: str, auth_flow: object) -> None:
    """Run PKCE browser-based login."""
    from bookshelf.oauth import authorization_code_flow as _auth_code_flow

    console.print("[cyan]Opening browser for authentication...[/cyan]")
    console.print("[dim]If the browser doesn't open, use --device-code instead.[/dim]")

    token_data = _auth_code_flow(api_url=base_url)

    _save_and_report(token_data, base_url)


def _login_device_code(base_url: str, start_fn: object, poll_fn: object) -> None:
    """Run device code login flow."""
    from bookshelf.oauth import poll_device_flow as _poll
    from bookshelf.oauth import start_device_flow as _start

    console.print("[cyan]Starting device code authentication...[/cyan]")

    device_flow = _start(api_url=base_url)

    # Display the code prominently
    console.print()
    console.print(f"[bold]Your code: [yellow]{device_flow.user_code}[/yellow][/bold]")
    console.print()
    uri = device_flow.verification_uri_complete
    console.print(f"Visit: [link={uri}]{uri}[/link]")
    console.print()

    with console.status("[cyan]Waiting for authorization...[/cyan]"):
        token_data = _poll(device_flow, api_url=base_url)

    _save_and_report(token_data, base_url)


def _save_and_report(token_data: dict, base_url: str) -> None:  # type: ignore[type-arg]
    """Save token data and print success message."""
    save_credentials(
        access_token=token_data["access_token"],
        token_type=token_data.get("token_type", "bearer"),
        expires_in=token_data.get("expires_in"),
        api_url=base_url,
        refresh_token=token_data.get("refresh_token"),
    )

    console.print("[green]v[/green] Login successful!")
    if token_data.get("expires_in"):
        console.print(f"[dim]Token expires in {token_data['expires_in']} seconds[/dim]")
    if token_data.get("refresh_token"):
        console.print("[dim]Refresh token stored for automatic renewal[/dim]")
    console.print(f"[dim]Credentials saved to {get_credentials_path()}[/dim]")


@auth_group.command(name="logout")
def logout() -> None:
    """Clear stored credentials."""
    if not is_authenticated():
        console.print("[yellow]![/yellow] Not currently logged in.")
        return

    clear_credentials()
    console.print("[green]v[/green] Logged out successfully.")
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

            # Show refresh token availability
            if creds["refresh_token"]:
                table.add_row("Refresh Token", "[green]Available[/green]")
            else:
                table.add_row("Refresh Token", "[yellow]Not available[/yellow]")

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
