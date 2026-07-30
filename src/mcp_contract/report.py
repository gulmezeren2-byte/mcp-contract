"""Render a diff for a human deciding whether to ship.

The ordering is the message: breaking first, because that is the only class that
stops the build; routing next, because it is the class people do not know to look for.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table
from rich.text import Text

from mcp_contract.model import ADDITIVE, BREAKING, COSMETIC, ROUTING, Contract, DiffReport

_STYLE = {BREAKING: "bold red", ROUTING: "yellow", ADDITIVE: "green", COSMETIC: "dim"}
_LABEL = {BREAKING: "breaking", ROUTING: "routing", ADDITIVE: "additive", COSMETIC: "cosmetic"}

_FANCY = {"sep": "·", "arrow": "→"}
_PLAIN = {"sep": "|", "arrow": "->"}


def glyphs() -> dict[str, str]:
    """Windows pipes output through the legacy code page, where these raise."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "".join(_FANCY.values()).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return _PLAIN
    return _FANCY


def render_contract(contract: Contract, console: Console | None = None) -> None:
    """Show a recorded surface: what the server promises right now."""
    console = console or Console()
    label = contract.server_name or "(unnamed server)"
    if contract.server_version:
        label += f" {contract.server_version}"
    console.print(Text(label, style="bold"))

    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("tool", no_wrap=True, style="cyan")
    table.add_column("arguments")
    for tool in sorted(contract.tools, key=lambda t: t.name):
        args = ", ".join(
            f"[bold]{a.name}[/bold]" if a.required else a.name
            for a in sorted(tool.arguments, key=lambda a: (not a.required, a.name))
        )
        table.add_row(tool.name, args or "[dim]none[/dim]")
    console.print(table)

    summary = f"{len(contract.tools)} tool(s)"
    with_output = sum(1 for t in contract.tools if t.output)
    if with_output:
        summary += f", {with_output} with a typed result"
    if contract.resources:
        summary += f", {len(contract.resources)} resource(s)"
    if contract.prompts:
        summary += f", {len(contract.prompts)} prompt(s)"
    console.print(f"{summary} [dim]— required arguments in bold[/dim]")


def render(report: DiffReport, console: Console | None = None) -> None:
    """Group by severity rather than tabulate.

    A squeezed four-column table breaks words in half on a narrow terminal, and this
    output is a list of findings, not a grid of values — so each change gets a
    headline it can keep on one line, and the explanation wraps underneath it.
    """
    console = console or Console()
    changes = report.sorted_changes()

    if not changes:
        console.print(
            f"[green]No change[/green] — {report.tools_checked} tool(s) match the contract."
        )
        return

    arrow = glyphs()["arrow"]
    current: str | None = None
    for change in changes:
        if change.severity != current:
            current = change.severity
            count = report.count(current)
            console.print()
            console.print(
                Text(
                    f"{_LABEL.get(current, current)} ({count})",
                    style=_STYLE.get(current, "bold"),
                )
            )
        where = change.tool
        if change.argument:
            where = f"{change.tool} {arrow} {change.argument}"
        console.print(f"  [cyan]{change.kind}[/cyan]  [bold]{where}[/bold]")
        console.print(f"      [dim]{change.detail}[/dim]")

    console.print()
    _summary(report, console)


def _summary(report: DiffReport, console: Console) -> None:
    sep = glyphs()["sep"]
    parts = [f"{report.tools_checked} tool(s)"]
    if report.breaking:
        parts.append(f"[bold red]{report.breaking} breaking[/bold red]")
    if report.routing:
        parts.append(f"[yellow]{report.routing} routing[/yellow]")
    if report.additive:
        parts.append(f"[green]{report.additive} additive[/green]")
    if report.cosmetic:
        parts.append(f"[dim]{report.cosmetic} cosmetic[/dim]")
    console.print(f" {sep} ".join(parts))

    if report.breaking:
        console.print(
            "[red]Breaking:[/red] agents built against the recorded contract will fail. "
            "Re-snapshot only if that is intended."
        )
    elif report.routing:
        console.print(
            "[yellow]Routing only:[/yellow] no call breaks, but the text an agent selects "
            "on changed. Re-snapshot once you have read the diff."
        )
