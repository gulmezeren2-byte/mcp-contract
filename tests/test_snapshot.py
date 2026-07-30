"""The contract file lives in git, so stability is a feature: the same server must
produce the same bytes, or every snapshot is a noisy diff nobody reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_contract.model import Argument, Contract, ToolContract
from mcp_contract.snapshot import SnapshotError, dumps, read, write

CONTRACT = Contract(
    tools=[
        ToolContract("b_tool", "second", (Argument("z", "string"), Argument("a", "integer"))),
        ToolContract(
            "a_tool", "first",
            (Argument("x", "string", required=True),),
            output=(Argument("id", "string", required=True), Argument("note", "string")),
        ),
    ],
    resources=["file:///b", "file:///a"],
    prompts=["translate", "summarize"],
    server_name="srv",
    server_version="1.2.3",
    command="srv --stdio",
)


def test_round_trip_preserves_the_contract() -> None:
    restored = Contract.from_dict(CONTRACT.to_dict())
    assert restored.server_name == "srv"
    assert restored.by_name["a_tool"].by_name["x"].required is True
    assert restored.by_name["b_tool"].by_name["a"].type == "integer"
    # output fields, resources and prompts survive too
    assert restored.by_name["a_tool"].output_by_name["id"].required is True
    assert sorted(restored.resources) == ["file:///a", "file:///b"]
    assert sorted(restored.prompts) == ["summarize", "translate"]


def test_serialisation_is_stable_regardless_of_input_order() -> None:
    # tools, resources and prompts all fed in a different order — output is identical
    shuffled = Contract(
        tools=[CONTRACT.tools[1], CONTRACT.tools[0]],
        resources=list(reversed(CONTRACT.resources)),
        prompts=list(reversed(CONTRACT.prompts)),
        server_name="srv",
        server_version="1.2.3",
        command="srv --stdio",
    )
    assert dumps(CONTRACT) == dumps(shuffled)


def test_file_ends_with_a_newline() -> None:
    assert dumps(CONTRACT).endswith("\n")


def test_non_ascii_stays_readable() -> None:
    turkish = Contract(tools=[ToolContract("t", "ÇŞB birim fiyat kataloğu")])
    assert "ÇŞB" in dumps(turkish)  # not ÇŞ...


def test_write_then_read(tmp_path: Path) -> None:
    path = tmp_path / "mcp-contract.json"
    write(CONTRACT, path)
    assert read(path).by_name["a_tool"].description == "first"


def test_missing_file_says_how_to_make_one(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="snapshot"):
        read(tmp_path / "nope.json")


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SnapshotError, match="valid JSON"):
        read(path)


def test_json_that_is_not_a_contract_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "other.json"
    path.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(SnapshotError, match="does not look like a contract"):
        read(path)
