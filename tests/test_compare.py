"""The classifier is the whole product: every case here is a promise about what
counts as breaking a caller, and what does not."""

from __future__ import annotations

from mcp_contract.compare import compare
from mcp_contract.model import (
    ADDITIVE,
    BREAKING,
    COSMETIC,
    ROUTING,
    Argument,
    Contract,
    PromptContract,
    ToolContract,
)


def tool(
    name: str,
    *args: Argument,
    description: str = "does a thing",
    output: tuple[Argument, ...] = (),
) -> ToolContract:
    return ToolContract(
        name=name, description=description, arguments=tuple(args), output=output
    )


def prompt(name: str, *args: Argument) -> PromptContract:
    return PromptContract(name=name, arguments=tuple(args))


def contract(
    *tools: ToolContract,
    version: str = "1.0.0",
    resources: list[str] | None = None,
    prompts: list[PromptContract | str] | None = None,
) -> Contract:
    # a bare string is shorthand for a prompt with no arguments
    prompt_objs = [PromptContract(name=p) if isinstance(p, str) else p for p in (prompts or [])]
    return Contract(
        tools=list(tools),
        resources=resources or [],
        prompts=prompt_objs,
        server_name="srv",
        server_version=version,
    )


def kinds(old: Contract, new: Contract) -> dict[str, str]:
    """kind -> severity, for compact assertions."""
    return {c.kind: c.severity for c in compare(old, new).changes}


# --------------------------------------------------------------------------- #
# nothing changed
# --------------------------------------------------------------------------- #
def test_identical_contracts_have_no_changes() -> None:
    a = contract(tool("t", Argument("x", "string", required=True)))
    report = compare(a, contract(tool("t", Argument("x", "string", required=True))))
    assert report.changes == []
    assert report.ok
    assert report.tools_checked == 1


# --------------------------------------------------------------------------- #
# breaking
# --------------------------------------------------------------------------- #
def test_removed_tool_is_breaking() -> None:
    assert kinds(contract(tool("gone")), contract())["tool-removed"] == BREAKING


def test_removed_argument_is_breaking() -> None:
    old = contract(tool("t", Argument("x"), Argument("y")))
    new = contract(tool("t", Argument("x")))
    assert kinds(old, new)["argument-removed"] == BREAKING


def test_new_required_argument_is_breaking() -> None:
    old = contract(tool("t", Argument("x")))
    new = contract(tool("t", Argument("x"), Argument("y", required=True)))
    assert kinds(old, new)["required-argument-added"] == BREAKING


def test_optional_becoming_required_is_breaking() -> None:
    old = contract(tool("t", Argument("x", "string", required=False)))
    new = contract(tool("t", Argument("x", "string", required=True)))
    assert kinds(old, new)["argument-now-required"] == BREAKING


def test_narrowed_type_is_breaking() -> None:
    old = contract(tool("t", Argument("x", "string|null")))
    new = contract(tool("t", Argument("x", "string")))
    assert kinds(old, new)["argument-type-changed"] == BREAKING


def test_unrelated_type_change_is_breaking() -> None:
    old = contract(tool("t", Argument("x", "string")))
    new = contract(tool("t", Argument("x", "integer")))
    assert kinds(old, new)["argument-type-changed"] == BREAKING


def test_removed_enum_value_is_breaking() -> None:
    old = contract(tool("t", Argument("mode", "string", enum=("fast", "slow"))))
    new = contract(tool("t", Argument("mode", "string", enum=("fast",))))
    assert kinds(old, new)["enum-value-removed"] == BREAKING


# --------------------------------------------------------------------------- #
# additive — reported, never fatal
# --------------------------------------------------------------------------- #
def test_new_tool_is_additive() -> None:
    assert kinds(contract(), contract(tool("fresh")))["tool-added"] == ADDITIVE


def test_new_optional_argument_is_additive() -> None:
    old = contract(tool("t", Argument("x")))
    new = contract(tool("t", Argument("x"), Argument("y", required=False)))
    assert kinds(old, new)["argument-added"] == ADDITIVE


def test_required_becoming_optional_is_additive() -> None:
    old = contract(tool("t", Argument("x", "string", required=True)))
    new = contract(tool("t", Argument("x", "string", required=False)))
    assert kinds(old, new)["argument-now-optional"] == ADDITIVE


def test_widened_type_is_additive() -> None:
    # every call that was valid before is still valid
    old = contract(tool("t", Argument("x", "string")))
    new = contract(tool("t", Argument("x", "string|null")))
    assert kinds(old, new)["argument-type-widened"] == ADDITIVE


def test_added_enum_value_is_additive() -> None:
    old = contract(tool("t", Argument("mode", "string", enum=("fast",))))
    new = contract(tool("t", Argument("mode", "string", enum=("fast", "slow"))))
    assert kinds(old, new)["enum-value-added"] == ADDITIVE


# --------------------------------------------------------------------------- #
# routing — the class a schema diff cannot see
# --------------------------------------------------------------------------- #
def test_tool_description_change_is_routing() -> None:
    old = contract(tool("t", description="Parse a catalog PDF."))
    new = contract(tool("t", description="Extract rows from a document."))
    assert kinds(old, new)["tool-description-changed"] == ROUTING


def test_argument_description_change_is_routing() -> None:
    old = contract(tool("t", Argument("x", "string", description="the input path")))
    new = contract(tool("t", Argument("x", "string", description="path to the PDF")))
    assert kinds(old, new)["argument-description-changed"] == ROUTING


def test_routing_change_alone_does_not_fail_the_build() -> None:
    old = contract(tool("t", description="one"))
    report = compare(old, contract(tool("t", description="two")))
    assert report.ok  # `--strict` is how you opt into failing on this
    assert report.routing == 1


# --------------------------------------------------------------------------- #
# cosmetic + ordering
# --------------------------------------------------------------------------- #
def test_server_version_change_is_cosmetic() -> None:
    old = contract(tool("t"), version="1.0.0")
    new = contract(tool("t"), version="1.1.0")
    assert kinds(old, new)["server-version-changed"] == COSMETIC


def test_breaking_sorts_before_everything_else() -> None:
    old = contract(tool("gone"), tool("t", Argument("x"), description="one"))
    new = contract(tool("t", Argument("x"), Argument("y"), description="two"))
    severities = [c.severity for c in compare(old, new).sorted_changes()]
    assert severities[0] == BREAKING
    rank = {BREAKING: 0, ROUTING: 1, ADDITIVE: 2}
    assert severities == sorted(severities, key=lambda s: rank[s])


# --------------------------------------------------------------------------- #
# output fields — the mirror of input arguments
# --------------------------------------------------------------------------- #
def test_removed_output_field_is_breaking() -> None:
    old = contract(tool("t", output=(Argument("id"), Argument("name"))))
    new = contract(tool("t", output=(Argument("id"),)))
    assert kinds(old, new)["output-field-removed"] == BREAKING


def test_new_output_field_is_additive() -> None:
    old = contract(tool("t", output=(Argument("id"),)))
    new = contract(tool("t", output=(Argument("id"), Argument("extra"))))
    assert kinds(old, new)["output-field-added"] == ADDITIVE


def test_widened_output_type_is_breaking_the_mirror() -> None:
    # input: widening is safe. output: widening can break a caller (may now get null).
    old = contract(tool("t", output=(Argument("v", "string"),)))
    new = contract(tool("t", output=(Argument("v", "string|null"),)))
    assert kinds(old, new)["output-type-widened"] == BREAKING


def test_narrowed_output_type_is_additive_the_mirror() -> None:
    old = contract(tool("t", output=(Argument("v", "string|null"),)))
    new = contract(tool("t", output=(Argument("v", "string"),)))
    assert kinds(old, new)["output-type-narrowed"] == ADDITIVE


def test_output_field_losing_its_guarantee_is_breaking() -> None:
    old = contract(tool("t", output=(Argument("id", "string", required=True),)))
    new = contract(tool("t", output=(Argument("id", "string", required=False),)))
    assert kinds(old, new)["output-now-optional"] == BREAKING


def test_new_output_enum_value_is_breaking() -> None:
    # a caller switching on the result may not handle a newly-possible value
    old = contract(tool("t", output=(Argument("status", "string", enum=("ok",)),)))
    new = contract(tool("t", output=(Argument("status", "string", enum=("ok", "degraded")),)))
    assert kinds(old, new)["output-enum-value-added"] == BREAKING


# --------------------------------------------------------------------------- #
# resources and prompts — presence
# --------------------------------------------------------------------------- #
def test_removed_resource_is_breaking() -> None:
    old = contract(tool("t"), resources=["file:///a", "file:///b"])
    new = contract(tool("t"), resources=["file:///a"])
    assert kinds(old, new)["resource-removed"] == BREAKING


def test_new_resource_is_additive() -> None:
    old = contract(tool("t"), resources=["file:///a"])
    new = contract(tool("t"), resources=["file:///a", "file:///b"])
    assert kinds(old, new)["resource-added"] == ADDITIVE


def test_removed_prompt_is_breaking() -> None:
    old = contract(tool("t"), prompts=["summarize", "translate"])
    new = contract(tool("t"), prompts=["summarize"])
    assert kinds(old, new)["prompt-removed"] == BREAKING


def test_removed_prompt_argument_is_breaking() -> None:
    old = contract(tool("t"), prompts=[prompt("p", Argument("topic"), Argument("lang"))])
    new = contract(tool("t"), prompts=[prompt("p", Argument("topic"))])
    assert kinds(old, new)["prompt-argument-removed"] == BREAKING


def test_new_required_prompt_argument_is_breaking() -> None:
    old = contract(tool("t"), prompts=[prompt("p", Argument("topic"))])
    added = prompt("p", Argument("topic"), Argument("lang", required=True))
    new = contract(tool("t"), prompts=[added])
    assert kinds(old, new)["prompt-required-argument-added"] == BREAKING


def test_new_optional_prompt_argument_is_additive() -> None:
    old = contract(tool("t"), prompts=[prompt("p", Argument("topic"))])
    new = contract(tool("t"), prompts=[prompt("p", Argument("topic"), Argument("lang"))])
    assert kinds(old, new)["prompt-argument-added"] == ADDITIVE


def test_prompt_argument_becoming_required_is_breaking() -> None:
    old = contract(tool("t"), prompts=[prompt("p", Argument("lang", required=False))])
    new = contract(tool("t"), prompts=[prompt("p", Argument("lang", required=True))])
    assert kinds(old, new)["prompt-argument-now-required"] == BREAKING


# --------------------------------------------------------------------------- #
# nested fields, and not punishing people for upgrading
#
# 0.4.0 resolves `$ref`, so it sees fields no earlier version could. Compared naively
# against a contract recorded by 0.3.0, every one of those newly-visible required
# fields reads as `required-argument-added` — breaking — on a server that never
# changed. A tool upgrade must never look like a server change.
# --------------------------------------------------------------------------- #
def nested_contract() -> Contract:
    return contract(
        tool(
            "search",
            Argument("filters", "object", required=True),
            Argument("filters.city", "string", required=True),
            Argument("filters.year", "integer", required=True),
            Argument("limit", "integer"),
        )
    )


def as_format_1(c: Contract) -> Contract:
    """What 0.3.0 would have recorded for the same server: no nested fields, and no
    type on the argument whose type was only knowable by resolving a $ref."""
    old = contract(tool("search", Argument("filters", None, required=True),
                        Argument("limit", "integer")))
    old.format = 1
    return old


def test_upgrading_the_tool_is_not_a_breaking_change() -> None:
    report = compare(as_format_1(nested_contract()), nested_contract())
    assert report.ok
    assert report.breaking == 0
    assert report.changes == []
    # but it does not go quiet about the gap
    assert report.notes
    assert "re-snapshot" in " ".join(report.notes).lower()


def test_an_old_contract_still_catches_a_real_top_level_break() -> None:
    # narrowing the comparison must not narrow what it protects
    live = contract(tool("search", Argument("filters", "object", required=True),
                         Argument("filters.city", "string", required=True)))
    report = compare(as_format_1(nested_contract()), live)
    assert kinds(as_format_1(nested_contract()), live)["argument-removed"] == BREAKING
    assert not report.ok


def test_a_current_contract_diffs_nested_fields_normally() -> None:
    old = nested_contract()
    new = contract(
        tool(
            "search",
            Argument("filters", "object", required=True),
            Argument("filters.city", "string", required=True),
            Argument("limit", "integer"),
        )
    )
    # renaming or dropping a field inside a nested model breaks a caller exactly as a
    # top-level one does — which is the entire point of resolving $ref
    assert kinds(old, new)["argument-removed"] == BREAKING


def test_probe_notes_reach_the_report() -> None:
    live = nested_contract()
    live.unrecorded = ["search: root: #/$defs/Node refers to itself"]
    report = compare(nested_contract(), live)
    assert report.ok  # a note is not a change
    assert report.notes == live.unrecorded
    assert report.to_dict()["notes"] == live.unrecorded


def test_report_counts_and_json_shape() -> None:
    old = contract(tool("gone"), tool("t", description="one"))
    report = compare(old, contract(tool("t", description="two")))
    data = report.to_dict()
    assert data["ok"] is False
    assert data["counts"]["breaking"] == 1
    assert data["counts"]["routing"] == 1
    assert data["changes"][0]["severity"] == BREAKING
