"""Tests for the pure parts of probing: turning a server's advertised JSON Schema
into a contract, and tolerating the SDK's field renames."""

from __future__ import annotations

import asyncio

from mcp.types import METHOD_NOT_FOUND

from mcp_contract.probe import (
    MAX_NESTING,
    MAX_PAGES,
    _all_pages,
    _argument_type,
    _error_code,
    _first_attr,
    surface_from_schema,
)

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
    assert tool.output == ()


def test_output_schema_is_captured() -> None:
    out_schema = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "count": {"type": "integer"}},
        "required": ["id"],
    }
    tool = surface_from_schema("parse", "Parse.", SCHEMA, out_schema)
    assert tool.arguments  # input still captured
    fields = tool.output_by_name
    assert set(fields) == {"id", "count"}
    assert fields["id"].required is True
    assert fields["count"].type == "integer"


def test_opaque_output_schema_yields_no_fields() -> None:
    # FastMCP tools returning a plain dict advertise {"additionalProperties": true}
    # with no properties — nothing to diff, and that's correct, not a miss.
    opaque = {"type": "object", "additionalProperties": True}
    tool = surface_from_schema("t", "", SCHEMA, opaque)
    assert tool.output == ()


def test_non_dict_property_does_not_explode() -> None:
    tool = surface_from_schema("odd", "", {"properties": {"x": "not-a-schema"}})
    assert tool.by_name["x"].type is None


def test_union_types_are_readable_and_stable() -> None:
    assert _argument_type({"type": ["string", "null"]}) == "null|string"
    assert _argument_type({"anyOf": [{"type": "string"}, {"type": "null"}]}) == "null|string"
    assert _argument_type({"type": "integer"}) == "integer"
    assert _argument_type({}) is None


# --------------------------------------------------------------------------- #
# $ref — the shape Pydantic actually emits, and the spec now requires resolving
#
# A tool taking a nested model advertises `{"$ref": "#/$defs/Filters"}` and puts the
# real fields under `$defs`. Reading only top-level `properties` records the argument
# with no type and no inner fields, so renaming an inner field is a breaking change
# reported as "no change" — a silent miss, the worst defect a contract tool can have.
# MCP spec 2026-07-28 (SEP-2106) makes $ref resolution a client requirement.
# --------------------------------------------------------------------------- #
PYDANTIC_NESTED = {
    "$defs": {
        "Filters": {
            "properties": {
                "city": {"title": "City", "type": "string"},
                "year": {"title": "Year", "type": "integer"},
            },
            "required": ["city", "year"],
            "title": "Filters",
            "type": "object",
        }
    },
    "properties": {
        "filters": {"$ref": "#/$defs/Filters"},
        "limit": {"default": 10, "title": "Limit", "type": "integer"},
    },
    "required": ["filters"],
    "title": "searchArguments",
    "type": "object",
}


def test_nested_model_fields_are_recorded() -> None:
    tool = surface_from_schema("search", "Search.", PYDANTIC_NESTED)
    args = tool.by_name
    # the parent is still there, and now says what it is
    assert args["filters"].required is True
    assert args["filters"].type == "object"
    # ...and the fields a caller actually has to get right are no longer invisible
    assert args["filters.city"].type == "string"
    assert args["filters.year"].type == "integer"
    assert args["limit"].type == "integer"


def test_nested_required_is_relative_to_its_parent() -> None:
    # `filters` itself is optional here, but a caller who supplies it must still
    # supply `city` — so an inner optional -> required is a real break, and is
    # recorded independently of the parent.
    schema = {
        "$defs": PYDANTIC_NESTED["$defs"],
        "properties": {"filters": {"$ref": "#/$defs/Filters"}},
        "required": [],
    }
    args = surface_from_schema("t", "", schema).by_name
    assert args["filters"].required is False
    assert args["filters.city"].required is True


def test_the_older_definitions_keyword_also_resolves() -> None:
    schema = {
        "definitions": {"P": {"type": "object", "properties": {"a": {"type": "string"}}}},
        "properties": {"p": {"$ref": "#/definitions/P"}},
    }
    assert surface_from_schema("t", "", schema).by_name["p.a"].type == "string"


def test_a_list_of_models_is_recorded_with_bracket_notation() -> None:
    schema = {
        "$defs": {"Tag": {"type": "object", "properties": {"name": {"type": "string"}}}},
        "properties": {"tags": {"type": "array", "items": {"$ref": "#/$defs/Tag"}}},
    }
    args = surface_from_schema("t", "", schema).by_name
    assert args["tags"].type == "array"
    assert args["tags[].name"].type == "string"


def test_an_optional_nested_model_inside_anyof_resolves() -> None:
    # `filters: Filters | None = None` is spelled as anyOf[$ref, null]
    schema = {
        "$defs": PYDANTIC_NESTED["$defs"],
        "properties": {
            "filters": {"anyOf": [{"$ref": "#/$defs/Filters"}, {"type": "null"}]}
        },
    }
    args = surface_from_schema("t", "", schema).by_name
    assert args["filters.city"].type == "string"


def test_nested_output_fields_are_recorded_too() -> None:
    out = {
        "$defs": {"Row": {"type": "object", "properties": {"id": {"type": "string"}}}},
        "properties": {"row": {"$ref": "#/$defs/Row"}},
        "required": ["row"],
    }
    tool = surface_from_schema("t", "", {"type": "object"}, out)
    assert tool.output_by_name["row.id"].type == "string"


def test_nested_names_stay_sorted_and_stable() -> None:
    tool = surface_from_schema("search", "", PYDANTIC_NESTED)
    names = [a.name for a in tool.arguments]
    assert names == sorted(names)
    # a parent sorts before its own children, so the file reads top-down
    assert names.index("filters") < names.index("filters.city")


# --------------------------------------------------------------------------- #
# bounded, and never silently truncated
# --------------------------------------------------------------------------- #
SELF_REFERENTIAL = {
    "$defs": {
        "Node": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "child": {"$ref": "#/$defs/Node"},
            },
        }
    },
    "properties": {"root": {"$ref": "#/$defs/Node"}},
}


def test_a_self_referential_model_terminates_and_says_so() -> None:
    notes: list[str] = []
    tool = surface_from_schema("t", "", SELF_REFERENTIAL, notes=notes)
    args = tool.by_name
    assert args["root.label"].type == "string"  # got at least one level
    # it stopped, and it did not stop quietly — a silent truncation in a
    # correctness tool is exactly the bug this portfolio exists to catch
    assert notes
    assert any("root" in n for n in notes)


def test_an_unresolvable_ref_is_left_alone_and_surfaced() -> None:
    # an external or unknown $ref is not something to guess about
    schema = {"properties": {"x": {"$ref": "https://example.com/other.json#/Thing"}}}
    notes: list[str] = []
    args = surface_from_schema("t", "", schema, notes=notes).by_name
    assert args["x"].type is None
    assert notes


def test_deep_nesting_stops_at_the_documented_limit() -> None:
    # five levels of object nesting; the cap is what keeps output bounded
    defs = {
        f"L{i}": {"type": "object", "properties": {"next": {"$ref": f"#/$defs/L{i + 1}"}}}
        for i in range(8)
    }
    defs["L8"] = {"type": "object", "properties": {"leaf": {"type": "string"}}}
    schema = {"$defs": defs, "properties": {"a": {"$ref": "#/$defs/L0"}}}
    notes: list[str] = []
    names = [a.name for a in surface_from_schema("t", "", schema, notes=notes).arguments]
    assert max(n.count(".") for n in names) <= MAX_NESTING
    assert notes  # the cut is reported, not hidden


# --------------------------------------------------------------------------- #
# listings are paginated, and the SDK does not follow the cursor for you
#
# Reading one page records a partial surface, and a tool that merely sat on page two
# would read as *removed* the next time anyone checked — a breaking change reported
# against a server that never changed.
# --------------------------------------------------------------------------- #
class _Page:
    def __init__(self, items: list[str], cursor: str | None) -> None:
        self.tools = items
        self.nextCursor = cursor  # noqa: N815 - the SDK's own spelling


def _paged(*pages: _Page):  # type: ignore[no-untyped-def]
    seen = []

    async def call(*, params=None):  # type: ignore[no-untyped-def]
        seen.append(getattr(params, "cursor", None))
        return pages[len(seen) - 1]

    call.cursors = seen  # type: ignore[attr-defined]
    return call


def test_every_page_is_read(anyio_backend: object = None) -> None:
    call = _paged(_Page(["a", "b"], "p2"), _Page(["c"], None))
    got = asyncio.run(_all_pages(call, "tools", [], "tools"))
    assert got == ["a", "b", "c"]
    # the first call sends no cursor, the second sends the one it was handed
    assert call.cursors == [None, "p2"]  # type: ignore[attr-defined]


def test_a_server_without_the_capability_is_an_empty_surface_not_an_error() -> None:
    # method-not-found means the server does not offer this at all — recording nothing
    # is the correct reading, and it is not worth telling anyone about
    class Missing(Exception):
        code = METHOD_NOT_FOUND

    async def call(*, params=None):  # type: ignore[no-untyped-def]
        raise Missing()

    notes: list[str] = []
    assert asyncio.run(_all_pages(call, "prompts", notes, "prompts")) == []
    assert notes == []


def test_any_other_failure_is_reported_rather_than_read_as_empty() -> None:
    # "the call failed" and "there are none" are different facts, and writing the
    # second when the first is true is how a contract quietly becomes fiction
    async def call(*, params=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("connection reset")

    notes: list[str] = []
    assert asyncio.run(_all_pages(call, "resources", notes, "resources")) == []
    assert notes and "connection reset" in notes[0]


def test_an_endlessly_paginating_server_stops_and_says_so() -> None:
    async def call(*, params=None):  # type: ignore[no-untyped-def]
        return _Page(["x"], "always-more")

    notes: list[str] = []
    got = asyncio.run(_all_pages(call, "tools", notes, "tools"))
    assert len(got) == MAX_PAGES
    assert notes and "kept paginating" in notes[0]


def test_error_code_is_read_from_both_sdk_shapes() -> None:
    # 2.x puts the code on the exception; 1.x wraps it in an ErrorData
    class New(Exception):
        code = METHOD_NOT_FOUND

    class Data:
        code = METHOD_NOT_FOUND

    class Old(Exception):
        error = Data()

    assert _error_code(New()) == METHOD_NOT_FOUND
    assert _error_code(Old()) == METHOD_NOT_FOUND
    assert _error_code(RuntimeError("plain")) is None


def test_first_attr_speaks_both_sdk_spellings() -> None:
    # the MCP Python SDK renamed inputSchema -> input_schema between releases
    class Old:
        inputSchema = {"type": "object"}

    class New:
        input_schema = {"type": "object"}

    assert _first_attr(Old(), "inputSchema", "input_schema") == {"type": "object"}
    assert _first_attr(New(), "inputSchema", "input_schema") == {"type": "object"}
    assert _first_attr(object(), "inputSchema", "input_schema") is None
