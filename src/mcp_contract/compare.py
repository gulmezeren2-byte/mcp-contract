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
    PromptContract,
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


def _compare_output_field(tool: str, old: Argument, new: Argument) -> list[Change]:
    """Output fields are the mirror of input arguments: the caller *receives* them,
    so the severities flip. Widening an output can break a caller (it may now get a
    shape it didn't handle); narrowing it is safe. A field that stops being guaranteed
    is breaking; a new guarantee is safe. A new possible enum value can break a caller
    that switches on it; a removed one cannot."""
    out: list[Change] = []

    if old.type != new.type:
        if _is_widening(old.type, new.type):
            out.append(
                Change("output-type-widened", BREAKING, tool,
                       f"output {old.type} -> {new.type}; a caller may now receive a value "
                       "it doesn't handle", old.name)
            )
        else:
            out.append(
                Change("output-type-narrowed", ADDITIVE, tool,
                       f"output {old.type} -> {new.type}; still within what callers handled",
                       old.name)
            )

    if old.required and not new.required:
        out.append(
            Change("output-now-optional", BREAKING, tool,
                   "an output field that was always present may now be missing", old.name)
        )
    elif not old.required and new.required:
        out.append(
            Change("output-now-guaranteed", ADDITIVE, tool,
                   "an output field is now always present", old.name)
        )

    old_enum, new_enum = set(old.enum or ()), set(new.enum or ())
    if old_enum or new_enum:
        added = new_enum - old_enum
        removed = old_enum - new_enum
        if added:
            out.append(
                Change("output-enum-value-added", BREAKING, tool,
                       f"output may now be {', '.join(sorted(added))}; a caller matching on "
                       "it may not handle that", old.name)
            )
        if removed:
            out.append(
                Change("output-enum-value-removed", ADDITIVE, tool,
                       f"output no longer returns {', '.join(sorted(removed))}", old.name)
            )

    return out


def _compare_prompt(old: PromptContract, new: PromptContract) -> list[Change]:
    """Prompt arguments are caller-supplied, so they break like tool inputs: remove
    one, or make one required, and a caller's existing invocation stops working."""
    out: list[Change] = []
    oa, na = old.by_name, new.by_name
    for name in sorted(set(oa) - set(na)):
        out.append(
            Change("prompt-argument-removed", BREAKING, old.name,
                   "a caller passing it now sends an unknown argument", name)
        )
    for name in sorted(set(na) - set(oa)):
        if na[name].required:
            out.append(
                Change("prompt-required-argument-added", BREAKING, old.name,
                       "new prompt argument is required; existing calls break", name)
            )
        else:
            out.append(
                Change("prompt-argument-added", ADDITIVE, old.name,
                       "new optional prompt argument", name)
            )
    for name in sorted(set(oa) & set(na)):
        if not oa[name].required and na[name].required:
            out.append(
                Change("prompt-argument-now-required", BREAKING, old.name,
                       "was optional, now required; calls that omitted it break", name)
            )
        elif oa[name].required and not na[name].required:
            out.append(
                Change("prompt-argument-now-optional", ADDITIVE, old.name,
                       "was required, now optional", name)
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

    # the output shape: a caller parses this, so a lost field is a real break
    old_out, new_out = old.output_by_name, new.output_by_name
    for name in sorted(set(old_out) - set(new_out)):
        out.append(
            Change("output-field-removed", BREAKING, old.name,
                   "a field the caller reads is gone from the result", name)
        )
    for name in sorted(set(new_out) - set(old_out)):
        out.append(
            Change("output-field-added", ADDITIVE, old.name, "new field in the result", name)
        )
    for name in sorted(set(old_out) & set(new_out)):
        out.extend(_compare_output_field(old.name, old_out[name], new_out[name]))

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

    # resources: presence only (a dropped resource breaks a caller as a dropped tool does)
    for name in sorted(set(old.resources) - set(new.resources)):
        changes.append(
            Change("resource-removed", BREAKING, name, "a resource the server exposed is gone")
        )
    for name in sorted(set(new.resources) - set(old.resources)):
        changes.append(Change("resource-added", ADDITIVE, name, "new resource"))

    # prompts: presence plus their arguments
    old_p = {p.name: p for p in old.prompts}
    new_p = {p.name: p for p in new.prompts}
    for name in sorted(set(old_p) - set(new_p)):
        changes.append(
            Change("prompt-removed", BREAKING, name, "a prompt the server exposed is gone")
        )
    for name in sorted(set(new_p) - set(old_p)):
        changes.append(Change("prompt-added", ADDITIVE, name, "new prompt"))
    for name in sorted(set(old_p) & set(new_p)):
        changes.extend(_compare_prompt(old_p[name], new_p[name]))

    if old.server_version and new.server_version and old.server_version != new.server_version:
        changes.append(
            Change("server-version-changed", COSMETIC, "(server)",
                   f"{old.server_version} -> {new.server_version}")
        )

    return DiffReport(changes=changes, tools_checked=len(new.tools))
