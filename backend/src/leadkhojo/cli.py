"""LeadKhojo command line.

The full pipeline without a browser. This exists so the backend is usable and
demonstrable before the UI is written — if week three slips, there is still a
working product.

    leadkhojo scan --csv domains.csv --out results
    leadkhojo scan --url acme.com --pdf
    leadkhojo plugins
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from leadkhojo.core.config import get_settings
from leadkhojo.core.logging import configure_logging
from leadkhojo.core.types import Url
from leadkhojo.core.utils.domains import canonical_domain, normalize_url
from leadkhojo.discovery.providers import CsvImportProvider, DiscoveredBusiness
from leadkhojo.export.csv_writer import write_csv
from leadkhojo.export.pdf_report import build_business_report, build_scan_summary
from leadkhojo.pipeline.runner import PipelineRunner, ScanResult
from leadkhojo.plugins.registry import build_engine, build_plugins

app = typer.Typer(
    add_completion=False,
    help="LeadKhojo - Website Intelligence Platform",
    no_args_is_help=True,
)
console = Console()


@app.command()
def scan(
    csv_path: Path | None = typer.Option(None, "--csv", help="CSV file with a domain column"),
    url: str | None = typer.Option(None, "--url", help="Single website to analyze"),
    out: Path = typer.Option(Path("leadkhojo-results"), "--out", help="Output file stem"),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
    pdf: bool = typer.Option(False, "--pdf", help="Also write PDF reports"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Discover, crawl, analyze, score and export."""
    settings = get_settings()
    configure_logging(level="DEBUG" if verbose else "WARNING", json_output=False)

    businesses = _collect_businesses(csv_path, url, limit)
    if not businesses:
        console.print("[red]No valid businesses to scan.[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"\n[bold]LeadKhojo[/bold]  scanning [cyan]{len(businesses)}[/cyan] business(es)\n"
    )

    try:
        engine = build_engine(settings.rules_dir)
    except Exception as exc:
        console.print(f"[red]Failed to load rules:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    runner = PipelineRunner(settings, engine)

    def progress(done: int, total: int, name: str) -> None:
        console.print(f"  [{done:>3}/{total}] {name[:52]}")

    result = asyncio.run(runner.run(businesses, on_progress=progress))
    _print_summary(result)
    _write_outputs(result, out, pdf=pdf)


@app.command()
def plugins() -> None:
    """List registered plugins and their execution order."""
    settings = get_settings()
    try:
        registered = build_plugins(settings.rules_dir)
        engine = build_engine(settings.rules_dir)
    except Exception as exc:
        console.print(f"[red]Failed to load plugins:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title="Registered plugins (in execution order)")
    table.add_column("#", justify="right", style="dim")
    table.add_column("ID", style="cyan")
    table.add_column("Kind")
    table.add_column("Depends on", style="dim")
    table.add_column("Provides", style="dim")

    order = {pid: i for i, pid in enumerate(engine.plugin_ids)}
    for plugin in sorted(registered, key=lambda p: order.get(p.meta.id, 999)):
        meta = plugin.meta
        table.add_row(
            str(order.get(meta.id, "?") + 1),
            meta.id,
            meta.kind.value,
            ", ".join(meta.depends_on) or "-",
            ", ".join(meta.provides) or "-",
        )

    console.print(table)


@app.command()
def rules() -> None:
    """Show how many rules are loaded."""
    from leadkhojo.opportunities.engine import load_opportunity_rules
    from leadkhojo.plugins.rules import load_rule_packs

    settings = get_settings()
    try:
        packs = load_rule_packs(settings.rules_dir)
        opportunity_rules = load_opportunity_rules(settings.rules_dir)
    except Exception as exc:
        console.print(f"[red]Failed to load rules:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"\n[bold]Rules directory:[/bold] {settings.rules_dir}")
    console.print(f"  technology fingerprints : [cyan]{len(packs.fingerprints)}[/cyan]")
    console.print(f"  known latest versions   : [cyan]{len(packs.latest_versions)}[/cyan]")
    console.print(f"  opportunity rules       : [cyan]{len(opportunity_rules)}[/cyan]\n")


# -- helpers ---------------------------------------------------------------


def _collect_businesses(
    csv_path: Path | None, url: str | None, limit: int
) -> tuple[DiscoveredBusiness, ...]:
    if csv_path is not None:
        if not csv_path.is_file():
            console.print(f"[red]File not found:[/red] {csv_path}")
            raise typer.Exit(code=1)
        provider = CsvImportProvider.from_path(csv_path)
        result = provider.parse(limit=limit)
        for error in result.errors[:10]:
            console.print(f"  [yellow]row {error.row}:[/yellow] {error.reason}")
        if result.errors:
            console.print(f"  [dim]{len(result.errors)} row(s) skipped[/dim]")
        return result.businesses

    if url is not None:
        normalized = normalize_url(url)
        domain = canonical_domain(url)
        if normalized is None or domain is None:
            console.print(f"[red]Not a usable URL:[/red] {url}")
            raise typer.Exit(code=1)
        return (
            DiscoveredBusiness(
                name=domain,
                website_url=Url(normalized),
                domain=domain,
                source="manual",
            ),
        )

    console.print("[red]Provide either --csv or --url.[/red]")
    raise typer.Exit(code=1)


def _print_summary(result: ScanResult) -> None:
    console.print(
        f"\n[bold]Done[/bold] in {result.duration_seconds:.1f}s  "
        f"[green]{len(result.succeeded)} analyzed[/green]  "
        f"[red]{len(result.failed)} failed[/red]\n"
    )

    ranked = result.ranked_by("opportunity")
    if not ranked:
        return

    table = Table(show_lines=False)
    table.add_column("Business", style="bold", max_width=26)
    table.add_column("Opp", justify="right")
    table.add_column("Sec", justify="right")
    table.add_column("Lead", justify="right")
    table.add_column("Contact", max_width=28)
    table.add_column("Top opportunity", max_width=38)

    for business_result in ranked[:25]:
        scores = business_result.scores
        table.add_row(
            business_result.business.name,
            str(scores.opportunity.total) if scores else "-",
            str(scores.security.total) if scores else "-",
            str(scores.lead.total) if scores else "-",
            str(business_result.artifact("contacts", "primary_email") or "-"),
            business_result.opportunities[0].title if business_result.opportunities else "-",
        )

    console.print(table)

    for failure in result.failed[:8]:
        reason = failure.failure_reason.value if failure.failure_reason else "unknown"
        console.print(f"  [dim]failed: {failure.business.domain} ({reason})[/dim]")


def _write_outputs(result: ScanResult, stem: Path, *, pdf: bool) -> None:
    csv_path = stem.with_suffix(".csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_bytes(write_csv(result.results))
    console.print(f"\n[green]CSV[/green]  {csv_path}")

    if not pdf:
        return

    summary_path = stem.with_suffix(".pdf")
    summary_path.write_bytes(build_scan_summary(result.results))
    console.print(f"[green]PDF[/green]  {summary_path}")

    reports_dir = stem.parent / f"{stem.name}-reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    for business_result in result.succeeded:
        name = (business_result.business.domain or "report").replace(".", "-")
        path = reports_dir / f"{name}.pdf"
        path.write_bytes(build_business_report(business_result))
    console.print(f"[green]PDF[/green]  {reports_dir}/ ({len(result.succeeded)} reports)")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
