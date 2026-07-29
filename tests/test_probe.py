"""Tests for the pure parts of probing: turning a server's advertised JSON Schema
into a contract, and tolerating the SDK's field renames."""

from __future__ import annotations

from mcp_contract.probe import _argument_type, _first_attr, surface_from_schema

SCHEMA = {
    "type": "object",
    "properties": {
        "pdf_path": {"type": "string", "description": "Path to the catalog."},
        "pages": {"type": "string"},
        "mode": {"type": "string", "enum": ["fast", "slow"]},
    },
    "required": ["pdf_path"],
}


def test_surface_captures_the_caller_visible_parts() -> None:
    tool = surface_from_schema("parse", "Parse a catalog.", SCHEMA)
    assert tool.name == "parse"
    assert tool.description == "Parse a catalog."
    args = tool.by_name
    assert args["pdf_path"].required is True
    assert args["pdf_path"].type == "string"
    assert args["pdf_path"].description == "Path to the catalog."
    assert args["pages"].required is False
    assert args["mode"].enum == ("fast", "slow")


def test_arguments_are_sorted_for_a_stable_file() -> None:
    tool = surface_from_schema("parse", "", SCHEMA)
    assert [a.name for a in tool.arguments] == sorted(a.name for a in tool.arguments)


def test_schema_without_properties_is_fine() -> None:
    tool = surface_from_schema("ping", "", {"type": "object"})
    assert tool.arguments == ()


def test_non_dict_property_does_not_explode() -> None:
    tool = surface_from_schema("odd", "", {"properties": {"x": "not-a-schema"}})
    assert tool.by_name["x"].type is None


def test_union_types_are_readable_and_stable() -> None:
    assert _argument_type({"type": ["string", "null"]}) == "null|string"
    assert _argument_type({"anyOf": [{"type": "string"}, {"type": "null"}]}) == "null|string"
    assert _argument_type({"type": "integer"}) == "integer"
    assert _argument_type({}) is None


def test_first_attr_speaks_both_sdk_spellings() -> None:
    # the MCP Python SDK renamed inputSchema -> input_schema between releases
    class Old:
        inputSchema = {"type": "object"}

    class New:
        input_schema = {"type": "object"}

    assert _first_attr(Old(), "inputSchema", "input_schema") == {"type": "object"}
    assert _first_attr(New(), "inputSchema", "input_schema") == {"type": "object"}
    assert _first_attr(object(), "inputSchema", "input_schema") is None
