"""Classify what changed, from the point of view of a caller already in the wild.

The question is never "did the JSON differ" — it always differs. The question is
whether a call that worked yesterday still works today, and whether an agent that
chose this tool yesterday would still choose it.
"""

from __future__ import annotations

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


# A type change is only breaking when it narrows what a caller may send. Widening —
# `string` becoming `string|null`, or an int accepted where only a string was — cannot
# break an existing valid call.
def _is_widening(old: str | None, new: str | None) -> bool:
    if not old or not new:
        return False
    old_parts = set(old.split("|"))
    new_parts = set(new.split("|"))
    return old_parts < new_parts


def _compare_argument(tool: str, old: Argument, new: Argument) -> list[Change]:
    out: list[Change] = []

    if old.type != new.type:
        if _is_widening(old.type, new.type):
            out.append(
                Change("argument-type-widened", ADDITIVE, tool,
                       f"type {old.type} -> {new.type}; existing calls still valid", old.name)
            )
        else:
            out.append(
                Change("argument-type-changed", BREAKING, tool,
                       f"type {old.type} -> {new.type}; a caller sending the old type breaks",
                       old.name)
            )

    if not old.required and new.required:
        out.append(
            Change("argument-now-required", BREAKING, tool,
                   "was optional, now required; every call that omitted it breaks", old.name)
        )
    elif old.required and not new.required:
        out.append(
            Change("argument-now-optional", ADDITIVE, tool,
                   "was required, now optional", old.name)
        )

    old_enum, new_enum = set(old.enum or ()), set(new.enum or ())
    if old_enum or new_enum:
        removed = old_enum - new_enum
        added = new_enum - old_enum
        if removed:
            out.append(
                Change("enum-value-removed", BREAKING, tool,
                       f"accepted value(s) gone: {', '.join(sorted(removed))}", old.name)
            )
        if added:
            out.append(
                Change("enum-value-added", ADDITIVE, tool,
                       f"new accepted value(s): {', '.join(sorted(added))}", old.name)
            )

    if old.description != new.description:
        out.append(
            Change("argument-description-changed", ROUTING, tool,
                   "the agent reads this to decide what to pass", old.name)
        )

    return out


def _compare_tool(old: ToolContract, new: ToolContract) -> list[Change]:
    out: list[Change] = []

    if old.description != new.description:
        out.append(
            Change(
                "tool-description-changed", ROUTING, old.name,
                "no call breaks, but the agent routes on this text — it may stop "
                "choosing this tool, or start choosing it for the wrong task",
            )
        )

    old_args, new_args = old.by_name, new.by_name

    for name in sorted(set(old_args) - set(new_args)):
        out.append(
            Change("argument-removed", BREAKING, old.name,
                   "a caller passing it now sends an unknown argument", name)
        )

    for name in sorted(set(new_args) - set(old_args)):
        arg = new_args[name]
        if arg.required:
            out.append(
                Change("required-argument-added", BREAKING, old.name,
                       "new argument is required; every existing call breaks", name)
            )
        else:
            out.append(
                Change("argument-added", ADDITIVE, old.name, "new optional argument", name)
            )

    for name in sorted(set(old_args) & set(new_args)):
        out.extend(_compare_argument(old.name, old_args[name], new_args[name]))

    return out


def compare(old: Contract, new: Contract) -> DiffReport:
    """Diff a recorded contract against a live one."""
    changes: list[Change] = []
    old_tools, new_tools = old.by_name, new.by_name

    for name in sorted(set(old_tools) - set(new_tools)):
        changes.append(
            Change("tool-removed", BREAKING, name,
                   "the tool is gone; an agent that depends on it fails")
        )

    for name in sorted(set(new_tools) - set(old_tools)):
        changes.append(Change("tool-added", ADDITIVE, name, "new tool"))

    for name in sorted(set(old_tools) & set(new_tools)):
        changes.extend(_compare_tool(old_tools[name], new_tools[name]))

    if old.server_version and new.server_version and old.server_version != new.server_version:
        changes.append(
            Change("server-version-changed", COSMETIC, "(server)",
                   f"{old.server_version} -> {new.server_version}")
        )

    return DiffReport(changes=changes, tools_checked=len(new.tools))
