"""mcp-contract command line.

    mcp-contract snapshot -- acikpoz-mcp     record the surface, commit the file
    mcp-contract check    -- acikpoz-mcp     fail when a change would break callers

The server command goes after `--` so its own flags are never mistaken for ours.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import typer
from rich.console import Console

from mcp_contract import __version__
from mcp_contract import report as _report
from mcp_contract import snapshot as _snapshot
from mcp_contract.compare import compare
from mcp_contract.probe import DEFAULT_TIMEOUT, ProbeError, probe
from mcp_contract.snapshot import DEFAULT_PATH, SnapshotError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Contract testing for MCP servers — catch a breaking change before your users do.",
)
_console = Console()
_err = Console(stderr=True)


def _use_utf8_output() -> None:
    """Tool names and descriptions are arbitrary text; on Windows a piped stdout gets
    the legacy code page, where non-ASCII raises UnicodeEncodeError and kills the run."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8", errors="replace")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"mcp-contract {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Print the version and exit.",
    ),
) -> None:
    """mcp-contract — snapshot an MCP server's tool surface, then hold it to it."""
    _use_utf8_output()


def _split(server: list[str]) -> tuple[str, list[str]]:
    if not server:
        _err.print(
            "[bold red]error:[/bold red] no server command. "
            "Try: mcp-contract check -- your-mcp-server"
        )
        raise typer.Exit(2)
    return server[0], list(server[1:])


def _probe_or_exit(server: list[str], timeout: float) -> object:
    command, args = _split(server)
    try:
        return probe(command, args, timeout=timeout)
    except ProbeError as exc:
        _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def snapshot(
    server: list[str] = typer.Argument(None, help="The server command, after `--`."),
    path: Path = typer.Option(
        DEFAULT_PATH, "--file", "-f", help="Where to write the contract."
    ),
    timeout: float = typer.Option(DEFAULT_TIMEOUT, "--timeout", help="Seconds to wait."),
    show: bool = typer.Option(True, "--show/--quiet", help="Print the recorded surface."),
) -> None:
    """Record the server's current tool surface. Commit the file."""
    contract = _probe_or_exit(server, timeout)
    written = _snapshot.write(contract, path)  # type: ignore[arg-type]
    if show:
        _report.render_contract(contract, _console)  # type: ignore[arg-type]
    _console.print(f"wrote [bold]{written}[/bold] — commit it so a change shows up in review")


@app.command()
def check(
    server: list[str] = typer.Argument(None, help="The server command, after `--`."),
    path: Path = typer.Option(DEFAULT_PATH, "--file", "-f", help="Contract to check against."),
    timeout: float = typer.Option(DEFAULT_TIMEOUT, "--timeout", help="Seconds to wait."),
    json_out: bool = typer.Option(False, "--json", help="Emit the diff as JSON."),
    strict: bool = typer.Option(
        False, "--strict", help="Fail on routing changes too, not just breaking ones."
    ),
) -> None:
    """Compare the live server against the recorded contract. Non-zero when it breaks."""
    try:
        recorded = _snapshot.read(path)
    except SnapshotError as exc:
        if json_out:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            _err.print(f"[bold red]error:[/bold red] {exc}")
        raise typer.Exit(2) from exc

    live = _probe_or_exit(server, timeout)
    diff = compare(recorded, live)  # type: ignore[arg-type]

    if json_out:
        typer.echo(json.dumps(diff.to_dict(), indent=2, ensure_ascii=False))
    else:
        _report.render(diff, _console)

    failed = not diff.ok or (strict and diff.routing > 0)
    raise typer.Exit(1 if failed else 0)


@app.command()
def show(
    server: list[str] = typer.Argument(None, help="The server command, after `--`."),
    timeout: float = typer.Option(DEFAULT_TIMEOUT, "--timeout", help="Seconds to wait."),
    json_out: bool = typer.Option(False, "--json", help="Emit the surface as JSON."),
) -> None:
    """Print a server's tool surface without recording anything."""
    contract = _probe_or_exit(server, timeout)
    if json_out:
        payload = contract.to_dict()  # type: ignore[attr-defined]
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _report.render_contract(contract, _console)  # type: ignore[arg-type]


if __name__ == "__main__":
    app()
