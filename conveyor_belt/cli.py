"""CLI entry point — invoked as `cb run`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console

from conveyor_belt.config import load_config

console = Console()


@click.group()
@click.version_option(package_name="conveyor-belt")
def main() -> None:
    """Conveyor Belt — agentic QA pipeline for code check-ins."""


@main.command()
@click.option("--pr", type=int, default=None, help="PR number to validate.")
@click.option(
    "--diff",
    type=str,
    default=None,
    help="Git ref range for diff (e.g. HEAD~1). Used when --pr is not set.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False),
    default=None,
    help="Path to conveyor-belt.yaml.",
)
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Repository root.",
)
@click.option(
    "--station",
    multiple=True,
    help="Run only specific station(s). Can be repeated.",
)
def run(
    pr: int | None,
    diff: str | None,
    config_path: str | None,
    repo: str,
    station: tuple[str, ...],
) -> None:
    """Run the QA pipeline against a PR or diff."""
    repo_root = str(Path(repo).resolve())
    # Look for config in repo root if not explicitly specified
    if config_path is None:
        repo_config = Path(repo_root) / "conveyor-belt.yaml"
        if repo_config.exists():
            config_path = str(repo_config)
    cfg = load_config(config_path)

    console.print(f"[bold green]▶ Conveyor Belt[/] — repo: {repo_root}")
    if pr:
        console.print(f"  PR #{pr}")
    elif diff:
        console.print(f"  diff ref: {diff}")
    else:
        console.print("  [yellow]No --pr or --diff supplied; will use staged changes.[/]")

    from conveyor_belt.orchestrator import Orchestrator

    orchestrator = Orchestrator(cfg, repo_root=repo_root)
    report = asyncio.run(
        orchestrator.run(
            pr_number=pr,
            diff_ref=diff,
            only_stations=list(station) if station else None,
        )
    )

    console.print()
    console.print(report.to_markdown())

    if not report.gate_passed:
        sys.exit(1)


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8000, show_default=True, type=int, help="Bind port.")
@click.option("--reload", is_flag=True, help="Auto-reload on code changes (dev mode).")
def serve(host: str, port: int, reload: bool) -> None:
    """Launch the visual web dashboard."""
    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        console.print(
            "[red]uvicorn is required. Install it with: pip install 'uvicorn[standard]'[/]"
        )
        sys.exit(1)

    console.print(f"[bold green]▶ Conveyor Belt UI[/] — http://{host}:{port}")
    uvicorn.run(
        "conveyor_belt.server:app",
        host=host,
        port=port,
        reload=reload,
    )


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False),
    default=None,
)
def validate_config(config_path: str | None) -> None:
    """Validate the conveyor-belt.yaml configuration file."""
    try:
        cfg = load_config(config_path)
        console.print("[green]✓ Configuration is valid.[/]")
        console.print(f"  Languages: {cfg.project.languages}")
        console.print(f"  Gate policy: {cfg.gate.policy}")
    except Exception as exc:
        console.print(f"[red]✗ Invalid configuration:[/] {exc}")
        sys.exit(1)
