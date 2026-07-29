"""mcp-contract — contract testing for MCP servers.

Snapshot the tool surface your server promises, commit it, and fail CI when a change
would break the agents that depend on it. Breaking, additive and *routing* changes are
told apart: a description edit breaks no call, but it can change which tool an agent
picks, and no schema diff will tell you.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from mcp_contract.compare import compare
from mcp_contract.model import (
    ADDITIVE,
    BREAKING,
    COSMETIC,
    ROUTING,
    Argument,
    Change,
    Contract,
    DiffReport,
    ToolContract,
)
from mcp_contract.probe import ProbeError, probe, surface_from_schema
from mcp_contract.snapshot import SnapshotError, dumps, read, write

try:
    __version__ = version("mcp-contract")
except PackageNotFoundError:  # pragma: no cover - only before install
    __version__ = "0.0.0"

__all__ = [
    "Argument",
    "ToolContract",
    "Contract",
    "Change",
    "DiffReport",
    "BREAKING",
    "ADDITIVE",
    "ROUTING",
    "COSMETIC",
    "probe",
    "ProbeError",
    "surface_from_schema",
    "compare",
    "read",
    "write",
    "dumps",
    "SnapshotError",
    "__version__",
]
