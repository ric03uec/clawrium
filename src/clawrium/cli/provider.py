"""Provider management commands for Clawrium."""

from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.table import Table

from clawrium.core.providers import (
    PROVIDER_MODELS,
    add_provider,
    fetch_ollama_models,
    get_models_for_type,
    get_provider,
    get_provider_api_key,
    load_providers,
    remove_provider,
    remove_provider_api_key,
    set_provider_api_key,
    update_provider,
    validate_ollama_url,
    validate_provider_name,
    validate_provider_type,
    DuplicateProviderError,
    InvalidOllamaUrlError,
    InvalidProviderNameError,
    InvalidProviderTypeError,
    OllamaConnectionError,
    ProvidersFileCorruptedError,
)

__all__ = ["provider_app"]

console = Console()

provider_app = typer.Typer(
    name="provider",
    help="Manage inference providers (LLM APIs)",
    no_args_is_help=True,
)


def _mask_api_key(key: str | None) -> str:
    """Mask API key for display, showing first 4 and last 4 chars."""
    if not key:
        return "-"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def _get_provider_types() -> list[str]:
    """Get list of supported provider types."""
    return sorted(PROVIDER_MODELS.keys())


@provider_app.command()
def add(
    name: str = typer.Argument(..., help="Unique name for this provider configuration"),
    provider_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help="Provider type (openai, anthropic, openrouter, bedrock, vertex, zai, ollama)",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Default model to use",
    ),
    url: Optional[str] = typer.Option(
        None,
        "--url",
        "-u",
        help="Server URL (required for Ollama)",
    ),
) -> None:
    """Add a new inference provider.

    API keys are collected securely via interactive prompt (not visible in process listing).

    Examples:
        clm provider add myopenai --type openai
        clm provider add local-llm --type ollama --url http://myserver.example.com:11434
        clm provider add work-claude --type anthropic --model claude-sonnet-4-20250514
    """
    # Validate provider name
    try:
        validate_provider_name(name)
    except InvalidProviderNameError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Validate provider type
    try:
        validate_provider_type(provider_type)
    except InvalidProviderTypeError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Check for duplicate
    try:
        existing = get_provider(name)
        if existing:
            console.print(f"[red]Error:[/red] Provider '{name}' already exists")
            raise typer.Exit(code=1)
    except ProvidersFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Handle Ollama specially - requires URL, no API key
    if provider_type == "ollama":
        if not url:
            url = typer.prompt("Ollama server URL", default="http://localhost:11434")

        # Validate URL for security (SSRF prevention)
        try:
            url = validate_ollama_url(url)
        except InvalidOllamaUrlError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        console.print(f"Connecting to Ollama server at {rich_escape(url)}...")
        try:
            available_models = fetch_ollama_models(url)
        except OllamaConnectionError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if not available_models:
            console.print("[yellow]Warning:[/yellow] No models found on Ollama server")
            console.print("Run 'ollama pull <model>' on the server to download models")
            raise typer.Exit(code=1)

        console.print(f"[green]Found {len(available_models)} models[/green]")

        # Select default model
        if model and model not in available_models:
            console.print(f"[yellow]Warning:[/yellow] Model '{rich_escape(model)}' not found on server")
            model = None

        if not model:
            console.print("\nAvailable models:")
            for i, m in enumerate(available_models, 1):
                console.print(f"  {i}. {rich_escape(m)}")

            choice = typer.prompt(
                "Select default model (number or name)",
                default="1",
            )
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(available_models):
                    model = available_models[idx]
                else:
                    model = choice
            except ValueError:
                model = choice

            if model not in available_models:
                console.print(f"[yellow]Warning:[/yellow] '{rich_escape(model)}' not in discovered models")
                if not typer.confirm("Continue anyway?"):
                    raise typer.Exit(code=0)

        # Build Ollama provider record (no API key stored)
        now = datetime.now(timezone.utc).isoformat()
        provider_record = {
            "name": name,
            "type": provider_type,
            "endpoint": url,
            "default_model": model,
            "available_models": available_models,
            "created_at": now,
            "updated_at": now,
        }

    else:
        # Cloud provider - requires API key
        models = get_models_for_type(provider_type)

        # Get API key securely via interactive prompt (B3 fix - no CLI flag)
        api_key = typer.prompt("API key", hide_input=True)

        if not api_key:
            console.print("[red]Error:[/red] API key is required")
            raise typer.Exit(code=1)

        # Select default model
        if model and models and model not in models:
            console.print(f"[yellow]Warning:[/yellow] Model '{rich_escape(model)}' not in known models for {provider_type}")
            if not typer.confirm("Continue anyway?"):
                raise typer.Exit(code=0)

        if not model and models:
            console.print(f"\nAvailable models for {provider_type}:")
            for i, m in enumerate(models, 1):
                console.print(f"  {i}. {rich_escape(m)}")

            choice = typer.prompt(
                "Select default model (number or name)",
                default="1",
            )
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(models):
                    model = models[idx]
                else:
                    model = choice
            except ValueError:
                model = choice

        # Build cloud provider record (API key stored separately in secrets)
        now = datetime.now(timezone.utc).isoformat()
        provider_record = {
            "name": name,
            "type": provider_type,
            "default_model": model,
            "created_at": now,
            "updated_at": now,
        }

        # Store API key securely (B1 fix)
        set_provider_api_key(name, api_key)

    # Add provider
    try:
        add_provider(provider_record)
    except DuplicateProviderError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    console.print(f"[green]Provider '{name}' added successfully![/green]")


@provider_app.command(name="list")
def list_providers() -> None:
    """List all configured providers."""
    try:
        providers = load_providers()
    except ProvidersFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not providers:
        console.print("No providers configured. Use 'clm provider add' to add a provider.")
        return

    table = Table(title="Configured Providers")

    table.add_column("Name", style="cyan")
    table.add_column("Type", style="white")
    table.add_column("Model", style="yellow")
    table.add_column("API Key", style="dim")
    table.add_column("Added", style="dim")

    for provider in providers:
        # Format added date
        added_at = provider.get("created_at", "")
        if added_at:
            try:
                dt = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
                added = dt.strftime("%Y-%m-%d")
            except ValueError:
                added = added_at[:10] if len(added_at) >= 10 else added_at
        else:
            added = "-"

        provider_name = provider.get("name", "?")
        provider_type = provider.get("type", "?")

        # For Ollama, show endpoint instead of masked key
        if provider_type == "ollama":
            key_display = rich_escape(provider.get("endpoint", "-"))
        else:
            # Fetch API key from secure storage
            api_key = get_provider_api_key(provider_name)
            key_display = _mask_api_key(api_key)

        table.add_row(
            rich_escape(provider_name),
            rich_escape(provider_type),
            rich_escape(provider.get("default_model", "-")),
            key_display,
            added,
        )

    console.print(table)


@provider_app.command()
def edit(
    name: str = typer.Argument(..., help="Provider name to edit"),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="New default model",
    ),
    url: Optional[str] = typer.Option(
        None,
        "--url",
        "-u",
        help="New server URL (Ollama only)",
    ),
    update_key: bool = typer.Option(
        False,
        "--update-key",
        help="Update API key (will prompt securely)",
    ),
) -> None:
    """Edit an existing provider configuration.

    Examples:
        clm provider edit myopenai --model gpt-4o-mini
        clm provider edit local-llm --url http://newserver.example.com:11434
        clm provider edit myopenai --update-key
    """
    # Check provider exists
    try:
        provider = get_provider(name)
    except ProvidersFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not provider:
        console.print(f"[red]Error:[/red] Provider '{name}' not found")
        raise typer.Exit(code=1)

    # Check if any changes requested
    if model is None and url is None and not update_key:
        console.print("[yellow]No changes specified.[/yellow] Use --model, --url, or --update-key to update.")
        raise typer.Exit(code=0)

    # Validate URL only makes sense for Ollama
    if url and provider.get("type") != "ollama":
        console.print("[red]Error:[/red] --url is only valid for Ollama providers")
        raise typer.Exit(code=1)

    # For Ollama with new URL, validate and refresh models
    available_models = None
    if url and provider.get("type") == "ollama":
        # Validate URL for security
        try:
            url = validate_ollama_url(url)
        except InvalidOllamaUrlError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        console.print(f"Connecting to Ollama server at {rich_escape(url)}...")
        try:
            available_models = fetch_ollama_models(url)
            console.print(f"[green]Found {len(available_models)} models[/green]")
        except OllamaConnectionError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

    # Handle API key update for non-Ollama providers
    if update_key:
        if provider.get("type") == "ollama":
            console.print("[yellow]Warning:[/yellow] Ollama providers don't use API keys")
        else:
            new_api_key = typer.prompt("New API key", hide_input=True)
            if new_api_key:
                set_provider_api_key(name, new_api_key)
                console.print("[green]API key updated.[/green]")
            else:
                console.print("[yellow]Warning:[/yellow] Empty API key provided, skipping update")

    def apply_updates(p: dict) -> dict:
        if model is not None:
            p["default_model"] = model
        if url is not None and p.get("type") == "ollama":
            p["endpoint"] = url
            if available_models is not None:
                p["available_models"] = available_models
        p["updated_at"] = datetime.now(timezone.utc).isoformat()
        return p

    # Only update provider record if model or url changed
    if model is not None or url is not None:
        if update_provider(name, apply_updates):
            console.print(f"[green]Provider '{name}' updated successfully![/green]")
        else:
            console.print("[red]Error:[/red] Failed to update provider")
            raise typer.Exit(code=1)
    elif update_key and provider.get("type") != "ollama":
        # Only API key was updated (already done above)
        console.print(f"[green]Provider '{name}' updated successfully![/green]")


@provider_app.command()
def remove(
    name: str = typer.Argument(..., help="Provider name to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Remove a provider configuration.

    Examples:
        clm provider remove myopenai
        clm provider remove old-provider --force
    """
    # Check provider exists
    try:
        provider = get_provider(name)
    except ProvidersFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not provider:
        console.print(f"[red]Error:[/red] Provider '{name}' not found")
        raise typer.Exit(code=1)

    # Confirmation (unless --force)
    if not force:
        confirmed = typer.confirm(
            f"Remove provider '{name}'? This cannot be undone."
        )
        if not confirmed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    if remove_provider(name):
        # Also remove API key from secure storage
        remove_provider_api_key(name)
        console.print(f"[green]Provider '{name}' removed successfully.[/green]")
    else:
        console.print("[red]Error:[/red] Failed to remove provider")
        raise typer.Exit(code=1)


@provider_app.command()
def types() -> None:
    """List supported provider types."""
    console.print("[bold]Supported provider types:[/bold]\n")

    for provider_type in _get_provider_types():
        config = PROVIDER_MODELS[provider_type]
        endpoint = config.get("endpoint")
        models = config.get("models")

        if provider_type == "ollama":
            console.print(f"  [cyan]{provider_type}[/cyan] - Self-hosted (dynamic model discovery)")
        elif endpoint:
            model_count = len(models) if models else 0
            console.print(f"  [cyan]{provider_type}[/cyan] - {model_count} models")
        else:
            model_count = len(models) if models else 0
            console.print(f"  [cyan]{provider_type}[/cyan] - {model_count} models (SDK-based)")


@provider_app.command()
def models(
    identifier: str = typer.Argument(
        ...,
        help="Provider type (openai, anthropic, etc.) or provider name",
    ),
) -> None:
    """List available models for a provider type or configured provider.

    Note: Provider types take precedence over configured provider names.

    Examples:
        clm provider models openai        # List models for OpenAI type
        clm provider models myopenai      # List models from saved provider config
    """
    # Check if it's a provider type
    if identifier in PROVIDER_MODELS:
        provider_type = identifier
        model_list = get_models_for_type(provider_type)

        if model_list is None:
            if provider_type == "ollama":
                console.print(
                    "[yellow]Ollama models are discovered dynamically.[/yellow]\n"
                    "Add an Ollama provider first, then query by provider name."
                )
            else:
                console.print(f"[yellow]No hardcoded models for {provider_type}[/yellow]")
            return

        console.print(f"[bold]Available models for {provider_type}:[/bold]\n")
        for m in model_list:
            console.print(f"  {rich_escape(m)}")
        return

    # Otherwise, check if it's a configured provider name
    try:
        provider = get_provider(identifier)
    except ProvidersFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if provider:
        provider_type = provider.get("type", "unknown")

        # For Ollama, show saved available_models
        if provider_type == "ollama":
            available = provider.get("available_models", [])
            if available:
                console.print(f"[bold]Models on '{identifier}' (Ollama):[/bold]\n")
                for m in available:
                    console.print(f"  {rich_escape(m)}")
            else:
                console.print(f"[yellow]No models cached for '{identifier}'.[/yellow]")
                console.print("Run 'clm provider refresh' to fetch models.")
            return

        # For cloud providers, show hardcoded models
        model_list = get_models_for_type(provider_type)
        if model_list:
            console.print(f"[bold]Available models for '{identifier}' ({provider_type}):[/bold]\n")
            for m in model_list:
                console.print(f"  {rich_escape(m)}")
        else:
            console.print(f"[yellow]No model list for provider type {provider_type}[/yellow]")
        return

    # Not found
    console.print(f"[red]Error:[/red] '{identifier}' is not a valid provider type or configured provider")
    console.print(f"\nValid provider types: {', '.join(_get_provider_types())}")
    raise typer.Exit(code=1)


@provider_app.command()
def refresh(
    name: str = typer.Argument(..., help="Ollama provider name to refresh"),
) -> None:
    """Refresh available models from an Ollama server.

    Re-fetches the model list from the Ollama server and updates the saved configuration.

    Examples:
        clm provider refresh local-llm
    """
    # Check provider exists
    try:
        provider = get_provider(name)
    except ProvidersFileCorruptedError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    if not provider:
        console.print(f"[red]Error:[/red] Provider '{name}' not found")
        raise typer.Exit(code=1)

    if provider.get("type") != "ollama":
        console.print("[yellow]Warning:[/yellow] 'refresh' only applies to Ollama providers")
        console.print(f"Provider '{name}' is type '{provider.get('type')}'")
        raise typer.Exit(code=0)

    endpoint = provider.get("endpoint")
    if not endpoint:
        console.print(f"[red]Error:[/red] Provider '{name}' has no endpoint configured")
        raise typer.Exit(code=1)

    console.print(f"Connecting to Ollama server at {rich_escape(endpoint)}...")
    try:
        available_models = fetch_ollama_models(endpoint)
    except OllamaConnectionError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    console.print(f"[green]Found {len(available_models)} models[/green]")

    def apply_refresh(p: dict) -> dict:
        p["available_models"] = available_models
        p["updated_at"] = datetime.now(timezone.utc).isoformat()
        return p

    if update_provider(name, apply_refresh):
        console.print(f"\n[green]Provider '{name}' updated with {len(available_models)} models:[/green]")
        for m in available_models:
            console.print(f"  {rich_escape(m)}")
    else:
        console.print("[red]Error:[/red] Failed to update provider")
        raise typer.Exit(code=1)
