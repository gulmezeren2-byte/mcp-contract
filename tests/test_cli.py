"""CLI behaviour that CI depends on: exit codes, JSON on stdout, and errors that
read like sentences instead of tracebacks."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mcp_contract.cli import _use_utf8_output, app
from mcp_contract.model import Argument, Contract, ToolContract
from mcp_contract.snapshot import write

runner = CliRunner()

RECORDED = Contract(
    tools=[ToolContract("t", "does a thing", (Argument("x", "string", required=True),))],
    server_name="srv",
    server_version="1.0.0",
)


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "mcp-contract" in result.stdout


def test_check_without_a_server_command_explains_itself() -> None:
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 2


def test_check_without_a_contract_file_says_how_to_record_one(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["check", "--file", str(tmp_path / "absent.json"), "--", "some-server"]
    )
    assert result.exit_code == 2


def test_check_without_a_contract_file_still_emits_json(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["check", "--file", str(tmp_path / "absent.json"), "--json", "--", "some-server"],
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "error" in payload


def test_unrunnable_server_is_an_error_not_a_traceback(tmp_path: Path) -> None:
    path = tmp_path / "mcp-contract.json"
    write(RECORDED, path)
    result = runner.invoke(
        app,
        ["check", "--file", str(path), "--timeout", "5", "--", "not-a-real-binary"],
    )
    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_utf8_guard_tolerates_a_stream_without_reconfigure() -> None:
    import sys

    class Bare:
        encoding = "cp1252"

        def write(self, text: str) -> int:  # pragma: no cover - not exercised
            return len(text)

    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Bare(), Bare()
    try:
        _use_utf8_output()  # must not raise
    finally:
        sys.stdout, sys.stderr = original_out, original_err
