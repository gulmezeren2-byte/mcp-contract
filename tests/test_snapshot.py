"""The contract file lives in git, so stability is a feature: the same server must
produce the same bytes, or every snapshot is a noisy diff nobody reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_contract.model import Argument, Contract, PromptContract, ToolContract
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
    prompts=[
        PromptContract("translate", (Argument("text", required=True), Argument("lang"))),
        PromptContract("summarize"),
    ],
    server_name="srv",
    server_version="1.2.3",
    command="srv --stdio",
)


def test_round_trip_preserves_the_contract() -> None:
    restored = Contract.from_dict(CONTRACT.to_dict())
    assert restored.server_name == "srv"
    assert restored.by_name["a_tool"].by_name["x"].required is True
    assert restored.by_name["b_tool"].by_name["a"].type == "integer"
    # output fields, resources and prompts (with their arguments) survive too
    assert restored.by_name["a_tool"].output_by_name["id"].required is True
    assert sorted(restored.resources) == ["file:///a", "file:///b"]
    prompts = {p.name: p for p in restored.prompts}
    assert sorted(prompts) == ["summarize", "translate"]
    assert prompts["translate"].by_name["text"].required is True


def test_reads_the_0_2_prompt_format(tmp_path: Path) -> None:
    # 0.2 wrote prompts as a bare list of names; an existing committed contract must
    # still read.
    path = tmp_path / "old.json"
    path.write_text(
        '{"server": {"name": "s", "version": "1"}, "tools": [], "prompts": ["a", "b"]}',
        encoding="utf-8",
    )
    restored = read(path)
    assert sorted(p.name for p in restored.prompts) == ["a", "b"]
    assert restored.prompts[0].arguments == ()


def test_the_format_is_recorded_so_an_old_file_is_recognisable(tmp_path: Path) -> None:
    # compare() needs to know how expressive the recorded file was, or upgrading the
    # tool reports breaking changes on a server that never changed
    path = tmp_path / "c.json"
    write(CONTRACT, path)
    assert '"format": 2' in path.read_text(encoding="utf-8")
    assert read(path).format == 2


def test_a_file_without_a_format_key_is_format_1(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text('{"server": {"name": "s"}, "tools": []}', encoding="utf-8")
    assert read(path).format == 1


def test_what_could_not_be_recorded_is_not_written_to_the_file() -> None:
    # it is a fact about one probe, not part of the promise; storing it would make the
    # committed file churn between runs
    noted = Contract(tools=[ToolContract("t", "d")], unrecorded=["t: x: cycle"])
    assert "unrecorded" not in dumps(noted)
    assert "cycle" not in dumps(noted)


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
