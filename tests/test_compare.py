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
    ToolContract,
)


def tool(name: str, *args: Argument, description: str = "does a thing") -> ToolContract:
    return ToolContract(name=name, description=description, arguments=tuple(args))


def contract(*tools: ToolContract, version: str = "1.0.0") -> Contract:
    return Contract(tools=list(tools), server_name="srv", server_version=version)


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


def test_report_counts_and_json_shape() -> None:
    old = contract(tool("gone"), tool("t", description="one"))
    report = compare(old, contract(tool("t", description="two")))
    data = report.to_dict()
    assert data["ok"] is False
    assert data["counts"]["breaking"] == 1
    assert data["counts"]["routing"] == 1
    assert data["changes"][0]["severity"] == BREAKING
