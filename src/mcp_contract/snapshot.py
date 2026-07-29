"""Read and write the committed contract file.

The file is meant to live in the repository next to the server, so the diff a
reviewer sees in a pull request *is* the change in the promise. That means it has to
be stable: same server, same file, byte for byte — otherwise every snapshot produces
noise and people stop reading it.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_contract.model import Contract

DEFAULT_PATH = Path("mcp-contract.json")


class SnapshotError(RuntimeError):
    """The contract file is missing or is not a contract."""


def dumps(contract: Contract) -> str:
    """Serialise deterministically: sorted, indented, newline-terminated."""
    return json.dumps(contract.to_dict(), indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def write(contract: Contract, path: Path = DEFAULT_PATH) -> Path:
    path.write_text(dumps(contract), encoding="utf-8")
    return path


def read(path: Path = DEFAULT_PATH) -> Contract:
    if not path.is_file():
        raise SnapshotError(
            f"no contract at {path}. Record one first: "
            "mcp-contract snapshot -- <server command>"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise SnapshotError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "tools" not in data:
        raise SnapshotError(f"{path} does not look like a contract (no `tools` key)")
    return Contract.from_dict(data)
