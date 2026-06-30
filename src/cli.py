"""
CLI entry point.
Uses Typer for argument parsing and Rich for pretty output.
Run with: python src/cli.py --help
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.text import Text

from src.pipeline import run

app = typer.Typer(
    name="candidate-transformer",
    help="Transform candidate data from multiple sources into a unified canonical profile.",
    add_completion=False,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        format="%(levelname)s [%(name)s] %(message)s",
        level=level,
        stream=sys.stderr,
    )


@app.command()
def transform(
    csv: Optional[Path] = typer.Option(None, "--csv", help="Path to recruiter CSV export"),
    resume: Optional[Path] = typer.Option(None, "--resume", help="Path to resume PDF"),
    linkedin: Optional[Path] = typer.Option(None, "--linkedin", help="Path to LinkedIn HTML export"),
    github: Optional[str] = typer.Option(
        None, "--github", help="Path to GitHub JSON or GitHub username/URL"
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", help="Path to projection config JSON"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write output to file instead of stdout"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
):
    """
    Transform candidate data from one or more sources into a canonical profile.

    At least one source (--csv, --resume, --linkedin, --github) is required.
    """
    _setup_logging(verbose)

    if not any([csv, resume, linkedin, github]):
        console.print("[red]Error:[/red] Provide at least one source (--csv, --resume, --linkedin, --github).")
        raise typer.Exit(code=1)

    console.print(
        Panel(
            Text("Candidate Transformer", justify="center", style="bold"),
            subtitle="extracting → normalizing → merging → scoring",
            border_style="dim",
        )
    )

    try:
        result = run(
            csv_path=str(csv) if csv else None,
            resume_path=str(resume) if resume else None,
            linkedin_path=str(linkedin) if linkedin else None,
            github_path=github,
            config_path=str(config) if config else None,
        )
    except ValueError as e:
        console.print(f"[red]Pipeline error:[/red] {e}")
        raise typer.Exit(code=1)

    json_str = json.dumps(result, indent=2, ensure_ascii=False)

    if output:
        output.write_text(json_str, encoding="utf-8")
        console.print(f"[green]Output written to:[/green] {output}")
    else:
        console.print(Panel(JSON(json_str), title="Canonical Profile", border_style="green"))

    # Summary line
    conf = result.get("overall_confidence", result.get("confidence_score", result.get("_overall_confidence", "N/A")))
    sources = result.get("sources_used", result.get("_sources_used", []))
    warnings = result.get("warnings", result.get("_warnings", []))
    console.print(
        f"\n[bold]Sources:[/bold] {', '.join(sources)} | "
        f"[bold]Confidence:[/bold] {conf} | "
        f"[bold]Warnings:[/bold] {len(warnings)}"
    )
    if warnings:
        for w in warnings:
            console.print(f"  [yellow]⚠[/yellow] {w}")


if __name__ == "__main__":
    app()
