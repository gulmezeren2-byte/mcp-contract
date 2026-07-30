"""What an MCP server promises, and how a promise can be broken.

A `Contract` is the surface an agent actually depends on: which tools exist, what
arguments they take, which of those are required, and — easy to overlook — what the
descriptions say, because an agent routes on the description, not on the schema.

Changes are classified by what they do to a caller already in the wild:

  * **breaking** — an existing, valid call stops working: a tool disappears, an
    argument is removed or renamed, an optional argument becomes required, a type
    narrows.
  * **additive** — new surface that no existing caller was using: a new tool, a new
    optional argument. Safe.
  * **routing** — the schema is untouched but the *description* changed. No call
    breaks, yet the agent may stop choosing this tool, or start choosing it for the
    wrong task. Silent, and invisible to a schema diff.
  * **cosmetic** — a title, or ordering. Noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BREAKING = "breaking"
ADDITIVE = "additive"
ROUTING = "routing"
COSMETIC = "cosmetic"

# Worst first, for sorting and for deciding an exit code.
SEVERITY_ORDER = {BREAKING: 0, ROUTING: 1, ADDITIVE: 2, COSMETIC: 3}

# How expressive the recorded file is. Bumped only when a new version can see
# something an older one could not, because that is exactly when a naive comparison
# would report a change on a server that never changed:
#   1 — top-level schema fields only (mcp-contract <= 0.3.0)
#   2 — nested fields behind `$ref` and composition keywords, dotted (`filters.city`)
# `compare()` reads the recorded format and holds itself to what that format could
# actually assert. See `_as_recorded` there.
FORMAT = 2


@dataclass(frozen=True)
class Argument:
    """One input argument of a tool, reduced to what a caller can break against."""

    name: str
    type: str | None = None
    required: bool = False
    description: str = ""
    enum: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "required": self.required}
        if self.type:
            out["type"] = self.type
        if self.description:
            out["description"] = self.description
        if self.enum:
            out["enum"] = list(self.enum)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Argument:
        enum = data.get("enum")
        return cls(
            name=str(data["name"]),
            type=data.get("type"),
            required=bool(data.get("required", False)),
            description=str(data.get("description") or ""),
            enum=tuple(str(e) for e in enum) if enum else None,
        )


@dataclass(frozen=True)
class ToolContract:
    """One tool as a caller sees it: the arguments it takes *in*, and the fields it
    promises *back*. Output fields are modelled with the same shape as arguments, but
    they are compared with mirrored severity — see compare.py — because the caller
    receives them rather than sends them."""

    name: str
    description: str = ""
    arguments: tuple[Argument, ...] = ()
    output: tuple[Argument, ...] = ()

    @property
    def by_name(self) -> dict[str, Argument]:
        return {a.name: a for a in self.arguments}

    @property
    def output_by_name(self) -> dict[str, Argument]:
        return {a.name: a for a in self.output}

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            # sorted so a re-snapshot of an unchanged server produces no git diff
            "arguments": [a.to_dict() for a in sorted(self.arguments, key=lambda a: a.name)],
        }
        if self.output:
            out["output"] = [a.to_dict() for a in sorted(self.output, key=lambda a: a.name)]
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolContract:
        return cls(
            name=str(data["name"]),
            description=str(data.get("description") or ""),
            arguments=tuple(Argument.from_dict(a) for a in data.get("arguments", [])),
            output=tuple(Argument.from_dict(a) for a in data.get("output", [])),
        )


@dataclass(frozen=True)
class PromptContract:
    """A prompt as a caller sees it: its name and the arguments it takes. Prompt
    arguments are caller-supplied, so they compare like tool *inputs* (removing one,
    or making one required, breaks a caller)."""

    name: str
    arguments: tuple[Argument, ...] = ()

    @property
    def by_name(self) -> dict[str, Argument]:
        return {a.name: a for a in self.arguments}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": [a.to_dict() for a in sorted(self.arguments, key=lambda a: a.name)],
        }

    @classmethod
    def from_dict(cls, data: Any) -> PromptContract:
        # Back-compat: 0.2 wrote prompts as a bare list of names.
        if isinstance(data, str):
            return cls(name=data)
        return cls(
            name=str(data["name"]),
            arguments=tuple(Argument.from_dict(a) for a in data.get("arguments", [])),
        )


@dataclass
class Contract:
    """A whole server surface, plus how it was obtained. Tools are the bulk of it,
    but a server also promises resources and prompts — dropping one breaks a caller
    just as surely — so they are carried too."""

    tools: list[ToolContract] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    prompts: list[PromptContract] = field(default_factory=list)
    server_name: str = ""
    server_version: str = ""
    command: str = ""
    format: int = FORMAT
    # What the schema described but the contract could not record — an unresolvable
    # `$ref`, a self-referential model, nesting past the limit. Deliberately *not*
    # serialised: it is a fact about this probe, not part of the promise, and writing
    # it would make the committed file less stable. Surfaced by the CLI instead.
    unrecorded: list[str] = field(default_factory=list)

    @property
    def by_name(self) -> dict[str, ToolContract]:
        return {t.name: t for t in self.tools}

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "format": self.format,
            "server": {"name": self.server_name, "version": self.server_version},
            "command": self.command,
            "tools": [t.to_dict() for t in sorted(self.tools, key=lambda t: t.name)],
        }
        if self.resources:
            out["resources"] = sorted(self.resources)
        if self.prompts:
            out["prompts"] = [p.to_dict() for p in sorted(self.prompts, key=lambda p: p.name)]
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Contract:
        server = data.get("server") or {}
        return cls(
            tools=[ToolContract.from_dict(t) for t in data.get("tools", [])],
            resources=[str(r) for r in data.get("resources", [])],
            prompts=[PromptContract.from_dict(p) for p in data.get("prompts", [])],
            server_name=str(server.get("name") or ""),
            server_version=str(server.get("version") or ""),
            command=str(data.get("command") or ""),
            # a file with no `format` key predates the concept: format 1
            format=int(data.get("format") or 1),
        )


@dataclass(frozen=True)
class Change:
    """One classified difference between the recorded contract and the live one."""

    kind: str  # stable kebab-case id, e.g. "tool-removed"
    severity: str
    tool: str
    detail: str
    argument: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "tool": self.tool,
            "argument": self.argument,
            "detail": self.detail,
        }


@dataclass
class DiffReport:
    """Every change, with the counts that decide the exit code."""

    changes: list[Change] = field(default_factory=list)
    tools_checked: int = 0
    # Things the reader should know that are not changes in the promise: a field the
    # schema described but the contract could not record, or a recorded contract too
    # old to express part of what was compared. Never affects the exit code.
    notes: list[str] = field(default_factory=list)

    def count(self, severity: str) -> int:
        return sum(1 for c in self.changes if c.severity == severity)

    @property
    def breaking(self) -> int:
        return self.count(BREAKING)

    @property
    def routing(self) -> int:
        return self.count(ROUTING)

    @property
    def additive(self) -> int:
        return self.count(ADDITIVE)

    @property
    def cosmetic(self) -> int:
        return self.count(COSMETIC)

    @property
    def ok(self) -> bool:
        """No breaking change. Additive and routing changes are reported, not fatal —
        `--strict` is how you say routing changes should stop the build too."""
        return self.breaking == 0

    def sorted_changes(self) -> list[Change]:
        return sorted(
            self.changes,
            key=lambda c: (SEVERITY_ORDER.get(c.severity, 9), c.tool, c.argument or "", c.kind),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "counts": {
                "tools": self.tools_checked,
                "breaking": self.breaking,
                "routing": self.routing,
                "additive": self.additive,
                "cosmetic": self.cosmetic,
            },
            "changes": [c.to_dict() for c in self.sorted_changes()],
            "notes": list(self.notes),
        }
