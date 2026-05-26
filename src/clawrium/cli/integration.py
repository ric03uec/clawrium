"""Integration management commands for Clawrium."""

import subprocess
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.table import Table

from clawrium.core.integrations import (
    INTEGRATION_TYPES,
    add_integration,
    get_credentials_for_type,
    get_integration,
    get_integration_credentials,
    load_integrations,
    remove_integration,
    set_integration_credential,
    validate_integration_name,
    validate_integration_type,
    DuplicateIntegrationError,
    IntegrationInUseError,
    IntegrationsFileCorruptedError,
    InvalidIntegrationNameError,
    InvalidIntegrationTypeError,
)

__all__ = ["integration_app"]

console = Console()

integration_app = typer.Typer(
    name="integration",
    help="Manage external service integrations (GitHub, Atlassian, etc.)",
    no_args_is_help=True,
    rich_markup_mode=None,
)


def _supported_types_help() -> str:
    return "Integration type (" + ", ".join(sorted(INTEGRATION_TYPES.keys())) + ")"


def _unknown_type_remediation(integration_type: str, name: str) -> str:
    # rich_escape both fields because integration_type comes from
    # integrations.json (potentially hand-edited) and could contain Rich
    # markup tokens like `[bold]`. name is regex-validated at add-time, but
    # escaping it costs nothing.
    safe_type = rich_escape(integration_type)
    safe_name = rich_escape(name)
    return (
        f"Integration type '{safe_type}' is not a known type "
        f"({', '.join(sorted(INTEGRATION_TYPES.keys()))}). "
        f"Run `clm integration remove {safe_name}` then "
        f"`clm integration add {safe_name} --type <valid-type>` to recover."
    )


def _mask_credential(value: str | None) -> str:
    """Mask credential for display, showing first 4 and last 4 chars."""
    if not value:
        return "-"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _sanitize_git_field(value: str) -> str:
    """Strip control characters that would inject gitconfig sections.

    A value like `Alice\n[core]\n    hooksPath = /tmp/evil` rendered into
    ~/.gitconfig opens a [core] section that git executes on every command.
    Strip CR/LF/NUL at ingest so the stored secret can never carry an
    injection payload — the template still defends-in-depth with a Jinja
    replace filter, but ingest is the right place to make values safe.
    """
    return value.replace("\r", "").replace("\n", " ").replace("\x00", "")


def _local_git_config(key: str) -> str:
    """Read a value from the operator's local --global git config.

    Returns empty string if git is not installed or the key is unset.
    """
    try:
        result = subprocess.run(
            ["git", "config", "--global", key],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode != 0:
        return ""
    # First line only — gitconfig values can technically be multi-line via
    # include directives, but for identity fields we want exactly one line.
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    return first_line.strip()


# Default values surfaced at prompt-time for the `git` integration.
# Identity defaults shell out to the operator's local --global git config.
# Static defaults match the template's Jinja default() fallbacks so that
# accepting the prompt and skipping the prompt produce the same rendered file.
_GIT_FIELD_DEFAULTS: dict[str, object] = {
    "GIT_USER_NAME": lambda: _local_git_config("user.name"),
    "GIT_USER_EMAIL": lambda: _local_git_config("user.email"),
    "GIT_INIT_DEFAULT_BRANCH": "main",
    "GIT_PULL_REBASE": "false",
    "GIT_CORE_EDITOR": "vim",
}


def _resolve_default(integration_type: str, key: str) -> str:
    """Resolve the prompt-time default for an integration credential.

    Currently only the `git` type carries defaults. Returns empty string
    when no default applies.
    """
    if integration_type != "git":
        return ""
    raw = _GIT_FIELD_DEFAULTS.get(key, "")
    if callable(raw):
        try:
            return raw() or ""
        except Exception:
            return ""
    return raw if isinstance(raw, str) else ""


def _get_integration_types() -> list[str]:
    """Get list of supported integration types."""
    return sorted(INTEGRATION_TYPES.keys())


@integration_app.command()
def types() -> None:
    """List supported integration types."""
    console.print("[bold]Supported integration types:[/bold]\n")

    for integration_type in _get_integration_types():
        config = INTEGRATION_TYPES[integration_type]
        description = config.get("description", "")
        credentials = config.get("credentials", [])
        required_count = sum(1 for c in credentials if c.get("required", False))

        console.print(f"  [cyan]{integration_type}[/cyan] - {description}")
        console.print(f"    Required credentials: {required_count}")


@integration_app.command(name="list")
def list_integrations() -> None:
    """List all configured integrations."""
    try:
        integrations = load_integrations()
    except IntegrationsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not integrations:
        console.print(
            "No integrations configured. Use 'clm integration add' to add an integration."
        )
        return

    table = Table(title="Configured Integrations")

    table.add_column("Name", style="cyan")
    table.add_column("Type", style="white")
    table.add_column("Credentials", style="dim")
    table.add_column("Added", style="dim")

    for integration in integrations:
        # Format added date
        added_at = integration.get("created_at", "")
        if added_at:
            try:
                dt = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
                added = dt.strftime("%Y-%m-%d")
            except ValueError:
                added = added_at[:10] if len(added_at) >= 10 else added_at
        else:
            added = "-"

        integration_name = integration.get("name", "?")
        integration_type = integration.get("type", "?")

        # Check credential status
        credentials = get_integration_credentials(integration_name)
        if credentials:
            cred_display = f"{len(credentials)} configured"
        else:
            cred_display = "none"

        # Surface unknown types (manual edits, removed types) at-a-glance so a
        # fleet audit catches them before configure runs.
        if integration_type not in INTEGRATION_TYPES:
            type_cell = f"[yellow]{rich_escape(integration_type)} (unknown)[/yellow]"
        else:
            type_cell = rich_escape(integration_type)

        table.add_row(
            rich_escape(integration_name),
            type_cell,
            cred_display,
            added,
        )

    console.print(table)


@integration_app.command()
def add(
    name: str = typer.Argument(..., help="Unique name for this integration"),
    integration_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help=_supported_types_help(),
    ),
) -> None:
    """Add a new external service integration.

    Credentials are collected securely via interactive prompts.

    Examples:
        clm integration add my-github --type github
        clm integration add work-atlassian --type atlassian
    """
    # Validate integration name
    try:
        validate_integration_name(name)
    except InvalidIntegrationNameError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Validate integration type
    try:
        validate_integration_type(integration_type)
    except InvalidIntegrationTypeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Check for duplicate
    try:
        existing = get_integration(name)
        if existing:
            console.print(
                f"[red]Error:[/red] Integration '{rich_escape(name)}' already exists"
            )
            raise typer.Exit(code=1)
    except IntegrationsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Get credential requirements for this type
    credential_defs = get_credentials_for_type(integration_type)
    credentials_to_store: list[tuple[str, str, str]] = []

    console.print(f"\n[bold]Configure {integration_type} integration:[/bold]\n")

    for cred_def in credential_defs:
        key = cred_def["key"]
        description = cred_def.get("description", key)
        required = cred_def.get("required", False)

        # Determine if this is a sensitive field (tokens, keys, secrets)
        is_sensitive = any(
            word in key.lower()
            for word in ["token", "key", "secret", "password", "api"]
        )

        # Prompt for value
        prompt_text = f"{description}"
        if not required:
            prompt_text += " (optional)"

        default_value = _resolve_default(integration_type, key)

        try:
            if is_sensitive:
                value = typer.prompt(
                    prompt_text, hide_input=True, default=default_value
                )
            else:
                value = typer.prompt(prompt_text, default=default_value)
        except (KeyboardInterrupt, EOFError):
            console.print("\nCancelled.")
            raise typer.Exit(code=1)

        if required and not value:
            console.print(f"[red]Error:[/red] {key} is required")
            raise typer.Exit(code=1)

        if value:
            if integration_type == "git":
                value = _sanitize_git_field(value)
            credentials_to_store.append((key, value, description))

    # Build integration record
    now = datetime.now(timezone.utc).isoformat()
    integration_record = {
        "name": name,
        "type": integration_type,
        "created_at": now,
        "updated_at": now,
    }

    # Add integration record first
    try:
        add_integration(integration_record)
    except DuplicateIntegrationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Store credentials after integration record is persisted
    for key, value, description in credentials_to_store:
        set_integration_credential(name, key, value, description)

    console.print(f"\n[green]Integration '{name}' added successfully![/green]")


@integration_app.command()
def show(
    name: str = typer.Argument(..., help="Integration name to show"),
) -> None:
    """Show details of a configured integration.

    Examples:
        clm integration show my-github
    """
    try:
        integration = get_integration(name)
    except IntegrationsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not integration:
        console.print(f"[red]Error:[/red] Integration '{rich_escape(name)}' not found")
        raise typer.Exit(code=1)

    integration_type = integration.get("type", "?")

    # Match `list`'s yellow `(unknown)` indicator so a stale entry is
    # spottable at-a-glance, not just at the error block below.
    if integration_type not in INTEGRATION_TYPES:
        type_display = f"[yellow]{rich_escape(integration_type)} (unknown)[/yellow]"
    else:
        type_display = rich_escape(integration_type)

    console.print(f"\n[bold]Integration: {rich_escape(name)}[/bold]\n")
    console.print(f"  Type: {type_display}")
    console.print(f"  Created: {integration.get('created_at', '-')}")
    console.print(f"  Updated: {integration.get('updated_at', '-')}")

    # Show credentials (masked)
    credentials = get_integration_credentials(name)
    if credentials:
        console.print("\n  [bold]Credentials:[/bold]")
        for key, value in credentials.items():
            console.print(f"    {key}: {_mask_credential(value)}")
    else:
        console.print("\n  [yellow]No credentials configured[/yellow]")

    # Show required credentials for this type. An unknown type (e.g., a
    # manual edit to integrations.json) surfaces a clean remediation message
    # and exits non-zero so scripts that `&&`-chain on `clm integration show`
    # halt rather than silently proceeding.
    try:
        credential_defs = get_credentials_for_type(integration_type)
    except InvalidIntegrationTypeError:
        console.print(
            f"\n  [red]Error:[/red] {_unknown_type_remediation(integration_type, name)}"
        )
        raise typer.Exit(code=1)
    required_keys = {c["key"] for c in credential_defs if c.get("required", False)}
    missing_keys = required_keys - set(credentials.keys())

    if missing_keys:
        console.print(
            f"\n  [yellow]Missing required:[/yellow] {', '.join(sorted(missing_keys))}"
        )


@integration_app.command()
def remove(
    name: str = typer.Argument(..., help="Integration name to remove"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip confirmation and remove even if in use"
    ),
) -> None:
    """Remove an integration configuration.

    This also removes all stored credentials for the integration.
    If the integration is assigned to agents, removal will be blocked
    unless --force is used.

    Examples:
        clm integration remove old-atlassian
        clm integration remove my-github --force
    """
    # Check integration exists
    try:
        integration = get_integration(name)
    except IntegrationsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not integration:
        console.print(f"[red]Error:[/red] Integration '{rich_escape(name)}' not found")
        raise typer.Exit(code=1)

    # Confirmation (unless --force)
    if not force:
        confirmed = typer.confirm(
            f"Remove integration '{rich_escape(name)}' and all its credentials? "
            "This cannot be undone."
        )
        if not confirmed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    try:
        if remove_integration(name, force=force):
            console.print(
                f"[green]Integration '{rich_escape(name)}' removed successfully.[/green]"
            )
        else:
            console.print("[red]Error:[/red] Failed to remove integration")
            raise typer.Exit(code=1)
    except IntegrationInUseError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            "[dim]Hint: Remove from agents first with 'clm agent integration remove' "
            "or use --force[/dim]"
        )
        raise typer.Exit(code=1)


@integration_app.command()
def credentials(
    name: str = typer.Argument(..., help="Integration name"),
    update: bool = typer.Option(
        False,
        "--update",
        "-u",
        help="Update credentials (will prompt for all values)",
    ),
) -> None:
    """View or update credentials for an integration.

    Without --update, shows current credential status (masked).
    With --update, prompts for new values for all credentials.

    Examples:
        clm integration credentials my-github
        clm integration credentials my-github --update
    """
    try:
        integration = get_integration(name)
    except IntegrationsFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not integration:
        console.print(f"[red]Error:[/red] Integration '{rich_escape(name)}' not found")
        raise typer.Exit(code=1)

    integration_type = integration.get("type", "?")

    if not update:
        # Show current credentials
        credentials_dict = get_integration_credentials(name)
        console.print(f"\n[bold]Credentials for {rich_escape(name)}:[/bold]\n")

        if credentials_dict:
            for key, value in sorted(credentials_dict.items()):
                console.print(f"  {key}: {_mask_credential(value)}")
        else:
            console.print("  No credentials configured")

        # Show what's required. Unknown type → exit 1 so scripts notice.
        try:
            credential_defs = get_credentials_for_type(integration_type)
        except InvalidIntegrationTypeError:
            console.print(
                f"\n  [red]Error:[/red] {_unknown_type_remediation(integration_type, name)}"
            )
            raise typer.Exit(code=1)
        required_keys = {c["key"] for c in credential_defs if c.get("required", False)}
        missing = required_keys - set(credentials_dict.keys())
        if missing:
            console.print(
                f"\n  [yellow]Missing required:[/yellow] {', '.join(sorted(missing))}"
            )

        return

    # Update mode - prompt for all credentials
    try:
        credential_defs = get_credentials_for_type(integration_type)
    except InvalidIntegrationTypeError:
        console.print(
            f"\n  [red]Error:[/red] {_unknown_type_remediation(integration_type, name)}"
        )
        raise typer.Exit(code=1)
    credentials_to_store: list[tuple[str, str, str]] = []

    console.print(f"\n[bold]Update credentials for {rich_escape(name)}:[/bold]\n")
    console.print("[dim]Press Enter to keep existing value[/dim]\n")

    current_credentials = get_integration_credentials(name)

    for cred_def in credential_defs:
        key = cred_def["key"]
        description = cred_def.get("description", key)
        required = cred_def.get("required", False)

        # Check if we have an existing value
        has_existing = key in current_credentials

        # Determine if this is a sensitive field
        is_sensitive = any(
            word in key.lower()
            for word in ["token", "key", "secret", "password", "api"]
        )

        # Prompt for value
        prompt_text = f"{description}"
        if has_existing:
            prompt_text += " [existing]"
        elif not required:
            prompt_text += " (optional)"

        default_value = (
            "" if has_existing else _resolve_default(integration_type, key)
        )

        try:
            if is_sensitive:
                value = typer.prompt(
                    prompt_text, hide_input=True, default=default_value
                )
            else:
                value = typer.prompt(prompt_text, default=default_value)
        except (KeyboardInterrupt, EOFError):
            console.print("\nCancelled.")
            raise typer.Exit(code=1)

        # If empty and we have existing, keep existing
        if not value and has_existing:
            continue

        if required and not value and not has_existing:
            console.print(f"[red]Error:[/red] {key} is required")
            raise typer.Exit(code=1)

        if value:
            if integration_type == "git":
                value = _sanitize_git_field(value)
            credentials_to_store.append((key, value, description))

    # Store updated credentials
    for key, value, description in credentials_to_store:
        set_integration_credential(name, key, value, description)

    if credentials_to_store:
        console.print(f"\n[green]Credentials updated for '{name}'.[/green]")
    else:
        console.print("\n[dim]No changes made.[/dim]")
