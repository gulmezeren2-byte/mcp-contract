"""Regenerate docs/demo.svg by probing a real MCP server.

The image in the README is not a mock-up: it is this script running `probe`
against a public, version-pinned server and rendering the same table the CLI
prints. If the output format changes, re-run me so the README never shows
something the tool no longer does.

The target is deliberately chosen so anyone can reproduce it:

* `@modelcontextprotocol/server-memory` is public and needs no credentials.
* The version is pinned, so the picture and the command agree.
* Probing is read-only — the server is started, asked for `tools/list`, and
  shut down. No tool is ever called.

Rich points its SVG at a CDN font; that rule is stripped afterwards so GitHub
(which blocks external fetches inside an SVG) renders the box-drawing with the
system monospace instead of empty boxes. Same treatment as ihalent's demo.

    uv run python scripts/make_demo_svg.py
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from mcp_contract.probe import probe
from mcp_contract.report import render_contract

ROOT = Path(__file__).parent.parent
SERVER = "@modelcontextprotocol/server-memory@2026.1.26"


def main() -> None:
    contract = probe("npx", ["-y", SERVER], timeout=120)
    console = Console(record=True, width=100, force_terminal=True)
    render_contract(contract, console)

    svg = console.export_svg(title=f"mcp-contract show -- npx -y {SERVER}")
    # Drop the CDN font-face so the SVG is self-contained on GitHub.
    svg = re.sub(r"@font-face\s*\{[^}]*?\}", "", svg, flags=re.DOTALL)

    out = ROOT / "docs" / "demo.svg"
    out.parent.mkdir(exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    print(
        f"wrote {out} ({len(contract.tools)} tools from "
        f"{contract.server_name} {contract.server_version})"
    )


if __name__ == "__main__":
    main()
