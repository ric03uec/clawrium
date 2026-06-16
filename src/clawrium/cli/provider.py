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
    CatalogLoadError,
    fetch_litellm_models,
    fetch_ollama_models,
    get_model_ids_for_provider,
    get_models_for_provider,
    get_provider,
    get_provider_api_key,
    get_provider_aws_credentials,
    load_providers,
    ProviderNotFoundError,
    remove_provider,
    remove_provider_api_key,
    remove_provider_aws_credentials,
    search_models,
    set_provider_api_key,
    set_provider_aws_credentials,
    update_provider,
    validate_litellm_url,
    validate_ollama_url,
    validate_provider_name,
    validate_provider_type,
    DuplicateProviderError,
    InvalidLiteLLMUrlError,
    InvalidOllamaUrlError,
    InvalidProviderNameError,
    InvalidProviderTypeError,
    LiteLLMConnectionError,
    OllamaConnectionError,
    ProvidersFileCorruptedError,
)

__all__ = ["provider_app"]

console = Console()

provider_app = typer.Typer(
    name="provider",
    help="Manage inference providers (LLM APIs)",
    no_args_is_help=True,
    rich_markup_mode=None,
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


def _format_context_window(tokens: int) -> str:
    """Format context window for display (e.g., 128000 -> 128K)."""
    if tokens == 0:
        return "-"
    if tokens >= 1_000_000:
        return f"{tokens // 1_000_000}M"
    if tokens >= 1000:
        return f"{tokens // 1000}K"
    return str(tokens)


def _get_model_suggestion(model_id: str, provider_type: str) -> str | None:
    """Find the closest matching model ID for suggestion.

    Args:
        model_id: Invalid model ID to find suggestion for
        provider_type: Provider type to search within

    Returns:
        Closest matching model ID, or None if no good match found
    """
    try:
        matches = search_models(model_id, provider_type=provider_type, limit=1)
        if matches:
            return matches[0]["id"]
    except (ProviderNotFoundError, CatalogLoadError):
        pass
    return None


def _display_models_with_metadata(
    models: list[dict], title: str, group_by_lab: bool = False
) -> None:
    """Display models in a formatted table with metadata.

    Args:
        models: List of model info dictionaries with id, name, lab, context_window
        title: Title to show above the table
        group_by_lab: Whether to group models by lab (for multi-lab providers)
    """
    if not models:
        console.print("[yellow]No models available.[/yellow]")
        return

    # Count unique labs to determine if grouping makes sense
    labs = sorted(set(m.get("lab", "Unknown") for m in models))

    if group_by_lab and len(labs) > 1:
        # Group by lab
        console.print(
            f"[bold]{title} ({len(models)} models from {len(labs)} labs)[/bold]\n"
        )
        models_by_lab: dict[str, list[dict]] = {}
        for m in models:
            lab = m.get("lab", "Unknown")
            if lab not in models_by_lab:
                models_by_lab[lab] = []
            models_by_lab[lab].append(m)

        for lab in sorted(models_by_lab.keys()):
            lab_models = models_by_lab[lab]
            console.print(f"[cyan]{lab}[/cyan] ({len(lab_models)} models)")
            table = Table(
                show_header=True, header_style="dim", box=None, padding=(0, 2)
            )
            table.add_column("ID", style="white")
            table.add_column("Name", style="yellow")
            table.add_column("Context", style="dim", justify="right")

            for m in lab_models:
                table.add_row(
                    rich_escape(m.get("id", "")),
                    rich_escape(m.get("name", "")),
                    _format_context_window(m.get("context_window", 0)),
                )
            console.print(table)
            console.print()
    else:
        # Single table without grouping
        console.print(f"[bold]{title} ({len(models)} models)[/bold]\n")
        table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
        table.add_column("ID", style="white")
        table.add_column("Name", style="yellow")
        table.add_column("Lab", style="cyan")
        table.add_column("Context", style="dim", justify="right")

        for m in models:
            table.add_row(
                rich_escape(m.get("id", "")),
                rich_escape(m.get("name", "")),
                rich_escape(m.get("lab", "")),
                _format_context_window(m.get("context_window", 0)),
            )
        console.print(table)


def _interactive_model_selection(provider_type: str) -> str | None:
    """Interactive model selection with fuzzy search.

    Args:
        provider_type: Provider type to get models for

    Returns:
        Selected model ID, or None if selection was cancelled
    """
    from fuzzyfinder import fuzzyfinder

    # Get models with full metadata
    try:
        models_data = get_models_for_provider(provider_type)
    except (ProviderNotFoundError, CatalogLoadError):
        return None

    if not models_data:
        return None

    # Build search index: combine id, name, and lab for fuzzy matching
    model_ids = [m["id"] for m in models_data]
    model_by_id = {m["id"]: m for m in models_data}

    # Create searchable strings: "id | name | lab"
    searchable = []
    for m in models_data:
        search_str = f"{m['id']} | {m['name']} | {m['lab']}"
        searchable.append((search_str, m["id"]))
    search_index = {s[0]: s[1] for s in searchable}

    console.print(f"\n[bold]Select a model ({len(model_ids)} available)[/bold]")
    console.print(
        "[dim]Type to search by ID, name, or lab. Enter a number or model ID to select.[/dim]\n"
    )

    # Show first 10 models as preview
    preview_count = min(10, len(models_data))
    for i, m in enumerate(models_data[:preview_count], 1):
        ctx = _format_context_window(m.get("context_window", 0))
        console.print(
            f"  {i:2}. {rich_escape(m['id'])} [dim]({m['name']}, {m['lab']}) [{ctx}][/dim]"
        )
    if len(models_data) > preview_count:
        console.print(f"  ... and {len(models_data) - preview_count} more")
    console.print()

    while True:
        choice = typer.prompt(
            "Enter number, model ID, or search term",
            default="1",
        )

        # Try as number first
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(model_ids):
                return model_ids[idx]
            console.print(f"[yellow]Invalid number. Enter 1-{len(model_ids)}[/yellow]")
            continue
        except ValueError:
            pass

        # Try as exact model ID
        if choice in model_ids:
            return choice

        # Try fuzzy search
        matches = list(fuzzyfinder(choice, search_index.keys()))
        if not matches:
            console.print(
                "[yellow]No matches found. Try a different search term.[/yellow]"
            )
            continue

        # Show top matches
        console.print(f"\n[bold]Matches for '{rich_escape(choice)}':[/bold]")
        match_ids = [search_index[m] for m in matches[:10]]
        for i, mid in enumerate(match_ids, 1):
            m = model_by_id[mid]
            ctx = _format_context_window(m.get("context_window", 0))
            console.print(
                f"  {i:2}. {rich_escape(m['id'])} [dim]({m['name']}, {m['lab']}) [{ctx}][/dim]"
            )
        if len(matches) > 10:
            console.print(f"  ... and {len(matches) - 10} more matches")
        console.print()

        # Prompt for selection from matches - loop until valid selection or new search
        while True:
            match_choice = typer.prompt(
                "Enter number to select, or type to search again",
                default="1",
            )

            try:
                idx = int(match_choice) - 1
                if 0 <= idx < len(match_ids):
                    return match_ids[idx]
                else:
                    console.print(
                        f"[yellow]Invalid selection. Enter 1-{len(match_ids)}[/yellow]"
                    )
                    continue
            except ValueError:
                # Non-numeric input: treat as new search query
                choice = match_choice
                break  # Exit inner loop to do new search


@provider_app.command()
def add(
    name: str = typer.Argument(..., help="Unique name for this provider configuration"),
    provider_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help="Provider type (openai, anthropic, openrouter, bedrock, vertex, zai, opencode, opencode-go, ollama, litellm)",
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
        help="Server URL (required for Ollama and LiteLLM)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip model validation (use for custom/unknown models)",
    ),
) -> None:
    """Add a new inference provider.

    API keys are collected securely via interactive prompt (not visible in process listing).

    Examples:
        clawctl provider add myopenai --type openai
        clawctl provider add local-llm --type ollama --url http://myserver.example.com:11434
        clawctl provider add work-claude --type anthropic --model claude-sonnet-4-20250514
        clawctl provider add custom --type openai --model my-custom-model --force
        clawctl provider add inx-litellm --type litellm --url http://192.168.1.17:4000 --model gemma4:31b
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
            console.print(
                f"[yellow]Warning:[/yellow] Model '{rich_escape(model)}' not found on server"
            )
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
                console.print(
                    f"[yellow]Warning:[/yellow] '{rich_escape(model)}' not in discovered models"
                )
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

        # Ollama doesn't require credentials
        credentials_to_store = None

    elif provider_type == "litellm":
        # LiteLLM is an OpenAI-compatible proxy: free-form URL + bearer key + model.
        if not url:
            console.print(
                "[red]Error:[/red] --url is required for litellm providers "
                "(e.g. http://192.168.1.17:4000)"
            )
            raise typer.Exit(code=1)

        if not model:
            console.print(
                "[red]Error:[/red] --model is required for litellm providers "
                "(the model ID served by the proxy)"
            )
            raise typer.Exit(code=1)

        try:
            url = validate_litellm_url(url)
        except InvalidLiteLLMUrlError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        api_key = typer.prompt("LiteLLM master key", hide_input=True)
        if not api_key:
            console.print("[red]Error:[/red] API key is required")
            raise typer.Exit(code=1)

        console.print(f"Probing LiteLLM proxy at {rich_escape(url)}...")
        available_models: list[str] = []
        try:
            available_models = fetch_litellm_models(url, api_key)
        except LiteLLMConnectionError as e:
            console.print(
                f"[yellow]Warning:[/yellow] could not list models from proxy: {e}"
            )
            console.print(
                "[dim]Provider will be created without an available_models cache; "
                "use 'clawctl provider refresh' once the proxy is reachable.[/dim]"
            )

        if available_models:
            console.print(
                f"[green]Found {len(available_models)} models on proxy[/green]"
            )
            if model not in available_models:
                console.print(
                    f"[yellow]Warning:[/yellow] '{rich_escape(model)}' was not "
                    "in the proxy's /v1/models response; saving anyway."
                )

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
        credentials_to_store = ("api_key", api_key)

    elif provider_type == "bedrock":
        # Bedrock requires AWS Access Key and Secret Key (not API key)
        try:
            models = get_model_ids_for_provider(provider_type)
        except (ProviderNotFoundError, CatalogLoadError):
            if not force:
                console.print(
                    f"[red]Error:[/red] Model catalog unavailable for {provider_type}. "
                    "Use --force to bypass validation."
                )
                raise typer.Exit(code=1)
            models = None

        console.print("[dim]AWS Bedrock requires Access Key and Secret Key[/dim]")

        # Get AWS Access Key securely via interactive prompt
        access_key = typer.prompt("AWS Access Key ID", hide_input=True)
        if access_key:
            console.print("[dim]**[/dim]")  # Visual feedback for paste
        if not access_key:
            console.print("[red]Error:[/red] AWS Access Key is required")
            raise typer.Exit(code=1)

        # Get AWS Secret Key securely via interactive prompt
        secret_key = typer.prompt("AWS Secret Access Key", hide_input=True)
        if secret_key:
            console.print("[dim]**[/dim]")  # Visual feedback for paste
        if not secret_key:
            console.print("[red]Error:[/red] AWS Secret Key is required")
            raise typer.Exit(code=1)

        # Validate model against catalog
        if model and models and model not in models:
            if force:
                console.print(
                    f"[yellow]Warning:[/yellow] Model '{rich_escape(model)}' not in catalog. "
                    "Proceeding with --force flag."
                )
            else:
                suggestion = _get_model_suggestion(model, provider_type)
                error_msg = (
                    f"Model '{rich_escape(model)}' not found for {provider_type}."
                )
                if suggestion:
                    error_msg += f" Did you mean '{rich_escape(suggestion)}'?"
                console.print(f"[red]Error:[/red] {error_msg}")
                console.print(
                    "[dim]Use --force to bypass validation for custom models.[/dim]"
                )
                raise typer.Exit(code=1)

        if not model:
            selected = _interactive_model_selection(provider_type)
            if selected:
                model = selected
            elif models:
                # Fallback to first model if interactive selection fails
                model = models[0]
                console.print(
                    f"[yellow]Using default model:[/yellow] {rich_escape(model)}"
                )

        # Build Bedrock provider record (AWS credentials stored separately in secrets)
        now = datetime.now(timezone.utc).isoformat()
        provider_record = {
            "name": name,
            "type": provider_type,
            "default_model": model,
            "created_at": now,
            "updated_at": now,
        }

        # Credentials will be stored after provider record is persisted
        credentials_to_store = ("aws", access_key, secret_key)

    else:
        # Cloud provider - requires API key
        try:
            models = get_model_ids_for_provider(provider_type)
        except (ProviderNotFoundError, CatalogLoadError):
            if not force:
                console.print(
                    f"[red]Error:[/red] Model catalog unavailable for {provider_type}. "
                    "Use --force to bypass validation."
                )
                raise typer.Exit(code=1)
            models = None

        # Get API key securely via interactive prompt (B3 fix - no CLI flag)
        api_key = typer.prompt("API key", hide_input=True)

        if not api_key:
            console.print("[red]Error:[/red] API key is required")
            raise typer.Exit(code=1)

        # Validate model against catalog
        if model and models and model not in models:
            if force:
                console.print(
                    f"[yellow]Warning:[/yellow] Model '{rich_escape(model)}' not in catalog. "
                    "Proceeding with --force flag."
                )
            else:
                suggestion = _get_model_suggestion(model, provider_type)
                error_msg = (
                    f"Model '{rich_escape(model)}' not found for {provider_type}."
                )
                if suggestion:
                    error_msg += f" Did you mean '{rich_escape(suggestion)}'?"
                console.print(f"[red]Error:[/red] {error_msg}")
                console.print(
                    "[dim]Use --force to bypass validation for custom models.[/dim]"
                )
                raise typer.Exit(code=1)

        if not model:
            selected = _interactive_model_selection(provider_type)
            if selected:
                model = selected
            elif models:
                # Fallback to first model if interactive selection fails
                model = models[0]
                console.print(
                    f"[yellow]Using default model:[/yellow] {rich_escape(model)}"
                )

        # Build cloud provider record (API key stored separately in secrets)
        now = datetime.now(timezone.utc).isoformat()
        provider_record = {
            "name": name,
            "type": provider_type,
            "default_model": model,
            "created_at": now,
            "updated_at": now,
        }

        # Credentials will be stored after provider record is persisted
        credentials_to_store = ("api_key", api_key)

    # Add provider record first, then store credentials (B1 fix - prevents orphaned secrets)
    try:
        add_provider(provider_record)
    except DuplicateProviderError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    # Store credentials only after provider record is successfully persisted
    if credentials_to_store is not None:
        if credentials_to_store[0] == "aws":
            set_provider_aws_credentials(
                name, credentials_to_store[1], credentials_to_store[2]
            )
        elif credentials_to_store[0] == "api_key":
            set_provider_api_key(name, credentials_to_store[1])

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
        console.print(
            "No providers configured. Use 'clawctl provider add' to add a provider."
        )
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
        elif provider_type == "litellm":
            api_key = get_provider_api_key(provider_name)
            endpoint = provider.get("endpoint", "-")
            key_display = (
                f"{rich_escape(endpoint)} ({_mask_api_key(api_key)})"
                if endpoint
                else _mask_api_key(api_key)
            )
        elif provider_type == "bedrock":
            # For Bedrock, show masked AWS Access Key
            access_key, secret_key = get_provider_aws_credentials(provider_name)
            if access_key and secret_key:
                key_display = _mask_api_key(access_key)
            else:
                key_display = "-"
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
        help="New server URL (Ollama and LiteLLM only)",
    ),
    update_key: bool = typer.Option(
        False,
        "--update-key",
        help="Update API key (will prompt securely)",
    ),
) -> None:
    """Edit an existing provider configuration.

    Examples:
        clawctl provider edit myopenai --model gpt-4o-mini
        clawctl provider edit local-llm --url http://newserver.example.com:11434
        clawctl provider edit inx-litellm --url http://192.168.1.17:4000 --update-key
        clawctl provider edit myopenai --update-key
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
        console.print(
            "[yellow]No changes specified.[/yellow] Use --model, --url, or --update-key to update."
        )
        raise typer.Exit(code=0)

    # Validate URL only makes sense for endpoint-backed providers
    if url and provider.get("type") not in ("ollama", "litellm"):
        console.print(
            "[red]Error:[/red] --url is only valid for Ollama and LiteLLM providers"
        )
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

    # For LiteLLM with new URL, validate and refresh models using the stored key
    if url and provider.get("type") == "litellm":
        try:
            url = validate_litellm_url(url)
        except InvalidLiteLLMUrlError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        existing_key = get_provider_api_key(name)
        if not existing_key:
            console.print(
                "[yellow]Warning:[/yellow] no stored API key for this provider; "
                "skipping model refresh. Use --update-key to set one."
            )
        else:
            console.print(f"Connecting to LiteLLM proxy at {rich_escape(url)}...")
            try:
                available_models = fetch_litellm_models(url, existing_key)
                console.print(
                    f"[green]Found {len(available_models)} models[/green]"
                )
            except LiteLLMConnectionError as e:
                console.print(
                    f"[yellow]Warning:[/yellow] could not list models: {e}"
                )
                available_models = None

    # Handle credential update for non-Ollama providers
    if update_key:
        if provider.get("type") == "ollama":
            console.print(
                "[yellow]Warning:[/yellow] Ollama providers don't use API keys. "
                "Use '--url' to update the server URL."
            )
            raise typer.Exit(code=0)
        elif provider.get("type") == "bedrock":
            # Bedrock uses AWS Access Key and Secret Key
            console.print("[dim]AWS Bedrock requires Access Key and Secret Key[/dim]")
            new_access_key = typer.prompt("New AWS Access Key ID", hide_input=True)
            if new_access_key:
                console.print("[dim]**[/dim]")  # Visual feedback for paste
            new_secret_key = typer.prompt("New AWS Secret Access Key", hide_input=True)
            if new_secret_key:
                console.print("[dim]**[/dim]")  # Visual feedback for paste
            if new_access_key and new_secret_key:
                set_provider_aws_credentials(name, new_access_key, new_secret_key)
                console.print("[green]AWS credentials updated.[/green]")
            else:
                console.print(
                    "[red]Error:[/red] Both Access Key and Secret Key are required"
                )
                raise typer.Exit(code=1)
        else:
            new_api_key = typer.prompt("New API key", hide_input=True)
            if new_api_key:
                set_provider_api_key(name, new_api_key)
                console.print("[green]API key updated.[/green]")
            else:
                console.print("[red]Error:[/red] API key cannot be empty")
                raise typer.Exit(code=1)

    def apply_updates(p: dict) -> dict:
        if model is not None:
            p["default_model"] = model
        if url is not None and p.get("type") in ("ollama", "litellm"):
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
        clawctl provider remove myopenai
        clawctl provider remove old-provider --force
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
        confirmed = typer.confirm(f"Remove provider '{name}'? This cannot be undone.")
        if not confirmed:
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    if remove_provider(name):
        # Also remove credentials from secure storage
        provider_type = provider.get("type")
        if provider_type == "bedrock":
            remove_provider_aws_credentials(name)
        elif provider_type != "ollama":
            remove_provider_api_key(name)
        console.print(f"[green]Provider '{name}' removed successfully.[/green]")
    else:
        console.print("[red]Error:[/red] Failed to remove provider")
        raise typer.Exit(code=1)


def _list_provider_types() -> None:
    """List all supported provider types."""
    console.print("[bold]Supported provider types:[/bold]\n")

    from clawrium.core.providers.models import get_model_count

    for provider_type in _get_provider_types():
        config = PROVIDER_MODELS[provider_type]
        endpoint = config.get("endpoint")

        if provider_type == "ollama":
            console.print(
                f"  [cyan]{provider_type}[/cyan] - Self-hosted (dynamic model discovery)"
            )
        elif endpoint:
            model_count = get_model_count(provider_type)
            console.print(f"  [cyan]{provider_type}[/cyan] - {model_count} models")
        else:
            model_count = get_model_count(provider_type)
            console.print(
                f"  [cyan]{provider_type}[/cyan] - {model_count} models (SDK-based)"
            )


def _show_models_for_type(provider_type: str) -> None:
    """Show models for a specific provider type."""
    if provider_type not in PROVIDER_MODELS:
        console.print(
            f"[red]Error:[/red] '{provider_type}' is not a valid provider type"
        )
        console.print(f"\nValid provider types: {', '.join(_get_provider_types())}")
        raise typer.Exit(code=1)

    # Handle Ollama specially (dynamic discovery)
    if provider_type == "ollama":
        console.print(
            "[yellow]Ollama models are discovered dynamically.[/yellow]\n"
            "Add an Ollama provider first, then query by provider name."
        )
        return

    # Get full model metadata from JSON catalog
    try:
        model_list = get_models_for_provider(provider_type)
    except ProviderNotFoundError:
        console.print(f"[yellow]No models available for {provider_type}[/yellow]")
        return
    except CatalogLoadError:
        console.print(
            f"[red]Error:[/red] Model catalog unavailable for {provider_type}."
        )
        return

    if not model_list:
        console.print(f"[yellow]No models available for {provider_type}[/yellow]")
        return

    # Multi-lab providers should group by lab
    multi_lab_providers = {"openrouter", "bedrock"}
    group_by_lab = provider_type in multi_lab_providers

    _display_models_with_metadata(
        model_list,
        f"Available models for {provider_type}",
        group_by_lab=group_by_lab,
    )


@provider_app.command()
def types(
    provider_type: Optional[str] = typer.Argument(
        None, help="Provider type to inspect (openai, anthropic, etc.)"
    ),
    action: Optional[str] = typer.Argument(
        None, help="Action to perform: 'models' to list available models"
    ),
) -> None:
    """List supported provider types or show details for a specific type.

    Examples:
        clawctl provider types                    # List all provider types
        clawctl provider types openai models      # List models for OpenAI
        clawctl provider types openrouter models  # List models grouped by lab
    """
    if provider_type is None:
        # No args: list all types
        _list_provider_types()
        return

    if action is None:
        # Provider type given but no action: show hint
        console.print(f"[bold]Provider type: {provider_type}[/bold]\n")
        if provider_type not in PROVIDER_MODELS:
            console.print(
                f"[red]Error:[/red] '{provider_type}' is not a valid provider type"
            )
            console.print(f"\nValid provider types: {', '.join(_get_provider_types())}")
            raise typer.Exit(code=1)
        console.print("Available actions:")
        console.print(
            f"  clawctl provider types {provider_type} models  # List available models"
        )
        return

    if action == "models":
        _show_models_for_type(provider_type)
        return

    # Unknown action
    console.print(f"[red]Error:[/red] Unknown action '{action}'")
    console.print("\nValid actions: models")
    raise typer.Exit(code=1)


@provider_app.command()
def refresh(
    name: str = typer.Argument(..., help="Provider name to refresh (Ollama or LiteLLM)"),
) -> None:
    """Refresh available models from an endpoint-backed provider.

    Re-fetches the model list and updates the saved configuration. Works for
    Ollama (hits /api/tags) and LiteLLM (hits /v1/models with bearer auth).

    Examples:
        clawctl provider refresh local-llm
        clawctl provider refresh inx-litellm
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

    ptype = provider.get("type")
    if ptype not in ("ollama", "litellm"):
        console.print(
            "[yellow]Warning:[/yellow] 'refresh' only applies to Ollama and "
            "LiteLLM providers"
        )
        console.print(f"Provider '{name}' is type '{ptype}'")
        raise typer.Exit(code=0)

    endpoint = provider.get("endpoint")
    if not endpoint:
        console.print(f"[red]Error:[/red] Provider '{name}' has no endpoint configured")
        raise typer.Exit(code=1)

    if ptype == "ollama":
        console.print(f"Connecting to Ollama server at {rich_escape(endpoint)}...")
        try:
            available_models = fetch_ollama_models(endpoint)
        except OllamaConnectionError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)
    else:  # litellm
        api_key = get_provider_api_key(name)
        if not api_key:
            console.print(
                f"[red]Error:[/red] Provider '{name}' has no stored API key. "
                "Use 'clawctl provider edit --update-key' to set one."
            )
            raise typer.Exit(code=1)
        console.print(f"Connecting to LiteLLM proxy at {rich_escape(endpoint)}...")
        try:
            available_models = fetch_litellm_models(endpoint, api_key)
        except LiteLLMConnectionError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

    console.print(f"[green]Found {len(available_models)} models[/green]")

    def apply_refresh(p: dict) -> dict:
        p["available_models"] = available_models
        p["updated_at"] = datetime.now(timezone.utc).isoformat()
        return p

    if update_provider(name, apply_refresh):
        console.print(
            f"\n[green]Provider '{name}' updated with {len(available_models)} models:[/green]"
        )
        for m in available_models:
            console.print(f"  {rich_escape(m)}")
    else:
        console.print("[red]Error:[/red] Failed to update provider")
        raise typer.Exit(code=1)
