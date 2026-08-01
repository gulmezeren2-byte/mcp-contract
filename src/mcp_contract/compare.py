"""Classify what changed, from the point of view of a caller already in the wild.

The question is never "did the JSON differ" — it always differs. The question is
whether a call that worked yesterday still works today, and whether an agent that
chose this tool yesterday would still choose it.
"""

from __future__ import annotations

from dataclasses import replace

from mcp_contract.model import (
    ADDITIVE,
    BREAKING,
    COSMETIC,
    FORMAT,
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


# For each behaviour hint: the value that grants the caller *more* freedom. Moving
# away from it withdraws a promise the caller may already be acting on — an agent
# host that auto-approved a read-only tool, or retried an idempotent one.
_SAFE_VALUE = {
    "read_only": True,
    "destructive": False,
    "idempotent": True,
    "open_world": False,
}
_HINT_DETAIL = {
    "read_only": (
        "the tool no longer promises to be read-only; a caller that auto-approved it "
        "on that basis is now approving a write"
    ),
    "destructive": (
        "the tool now declares itself destructive; a caller that ran it unattended "
        "was not expecting that"
    ),
    "idempotent": (
        "the tool no longer promises to be idempotent; a caller that retries on "
        "timeout may now double-apply it"
    ),
    "open_world": (
        "the tool now declares it touches an open world of external entities"
    ),
}


def _compare_behaviour(tool: str, old: ToolContract, new: ToolContract) -> list[Change]:
    """Diff the advertised behaviour hints.

    These are promises about *how* a tool acts, and a caller acts on them before ever
    reading a schema. Reversing one, or withdrawing it entirely, changes what is safe
    to do with the tool while every argument stays byte-identical — which is exactly
    the kind of change a schema diff cannot see.
    """
    out: list[Change] = []
    a, b = old.behaviour, new.behaviour

    for hint, safe in _SAFE_VALUE.items():
        was, now = getattr(a, hint), getattr(b, hint)
        if was == now:
            continue
        if was is None:
            # newly declared: information the caller did not have before, not a change
            # in what the tool was already allowed to do
            out.append(
                Change(f"behaviour-{hint}-declared", ADDITIVE, tool,
                       f"now declares {hint}={str(now).lower()}", hint)
            )
        elif now is None:
            out.append(
                Change(f"behaviour-{hint}-withdrawn", BREAKING, tool,
                       f"no longer declares {hint}; a caller relying on that guarantee "
                       "has nothing to rely on", hint)
            )
        elif was == safe:
            out.append(
                Change(f"behaviour-{hint}-reversed", BREAKING, tool,
                       _HINT_DETAIL[hint], hint)
            )
        else:
            out.append(
                Change(f"behaviour-{hint}-relaxed", ADDITIVE, tool,
                       f"{hint} is now {str(now).lower()}, which constrains the tool "
                       "further rather than less", hint)
            )

    if a.task_support != b.task_support:
        # `required` and `forbidden` are opposite ends: a caller written for one
        # cannot call a server that has moved to the other
        severity = BREAKING if (a.task_support and b.task_support) else (
            BREAKING if a.task_support else ADDITIVE
        )
        out.append(
            Change("task-support-changed", severity, tool,
                   f"task support {a.task_support or '(undeclared)'} -> "
                   f"{b.task_support or '(undeclared)'}", "task_support")
        )

    return out


def _compare_tool(old: ToolContract, new: ToolContract) -> list[Change]:
    out: list[Change] = []

    if old.title != new.title:
        out.append(
            Change(
                "tool-title-changed", ROUTING, old.name,
                "the display name a human or an agent picks this tool by changed",
            )
        )

    out.extend(_compare_behaviour(old.name, old, new))

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


def _is_child(child: str, parent: str) -> bool:
    """`filters.city` and `tags[].name` are children; `filtersX` is not."""
    return child.startswith(f"{parent}.") or child.startswith(f"{parent}[].")


def _narrow(prior: dict[str, Argument], fields: tuple[Argument, ...]) -> tuple[Argument, ...]:
    """Present these fields the way a format-1 contract recorded them.

    Nested fields are dropped — that format could not express them, so it never
    promised anything about them. And where a parent's type is only knowable by
    resolving a `$ref`, the old contract recorded none; keeping the newly-resolved
    type would read as a type change. Both are newly-*visible* information, not
    changes in the promise, and reporting them as breaking would fail the build of
    every user who did nothing but upgrade.
    """
    kept = []
    for arg in fields:
        if any(_is_child(arg.name, p) for p in (a.name for a in fields)):
            continue  # nested: not expressible in format 1
        recorded = prior.get(arg.name)
        has_children = any(_is_child(other.name, arg.name) for other in fields)
        if has_children and recorded is not None and recorded.type is None:
            arg = replace(arg, type=None)
        kept.append(arg)
    return tuple(kept)


def _as_recorded(old: Contract, new: Contract) -> tuple[Contract, int]:
    """Reduce the live contract to what the recorded format could express, and say
    how many fields that hid. Comparing like with like is the whole point: a tool
    upgrade must never look like a server change."""
    hidden = 0
    tools = []
    for tool in new.tools:
        recorded = old.by_name.get(tool.name)
        arguments = _narrow(recorded.by_name if recorded else {}, tool.arguments)
        output = _narrow(recorded.output_by_name if recorded else {}, tool.output)
        hidden += (len(tool.arguments) - len(arguments)) + (len(tool.output) - len(output))
        tools.append(replace(tool, arguments=arguments, output=output))
    return replace(new, tools=tools), hidden


def compare(old: Contract, new: Contract) -> DiffReport:
    """Diff a recorded contract against a live one."""
    changes: list[Change] = []
    notes: list[str] = list(new.unrecorded)

    if old.format < FORMAT:
        new, hidden = _as_recorded(old, new)
        if hidden:
            notes.append(
                f"this contract predates nested-field tracking, so {hidden} nested "
                "field(s) are not being checked. Re-snapshot to start checking them."
            )

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

    return DiffReport(changes=changes, tools_checked=len(new.tools), notes=notes)
