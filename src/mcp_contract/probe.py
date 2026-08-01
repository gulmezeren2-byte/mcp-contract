"""Ask a running MCP server what it offers.

The server is started the way its users start it — as a subprocess over stdio — and
asked for `tools/list`. Nothing is called, so probing is side-effect free: this is a
question about the surface, not a test of behaviour.

The JSON Schema that comes back is reduced to the part a caller can break against
(argument names, types, required-ness, descriptions, enums). Keeping the whole raw
schema would make every internal reformat look like a change; keeping less would miss
real breaks.
"""

from __future__ import annotations

import asyncio
import inspect
import shlex
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import METHOD_NOT_FOUND

try:  # the `params=` form of pagination arrived in SDK 1.20; before that, `cursor=`
    from mcp.types import PaginatedRequestParams
except ImportError:  # pragma: no cover - depends on the installed SDK
    PaginatedRequestParams = None  # type: ignore[assignment, misc]

from mcp_contract.model import Argument, Behaviour, Contract, PromptContract, ToolContract

DEFAULT_TIMEOUT = 60.0

# A listing is paginated; a server still handing out cursors after this many pages is
# broken rather than large, and following it forever would hang the probe.
MAX_PAGES = 100

# How deep a recorded field name may go (`a.b.c.d` is four levels). Deep enough for
# real schemas, shallow enough that the contract file stays readable and bounded —
# and, unlike an unbounded walk, it terminates on a schema that refers to itself.
MAX_NESTING = 4
# A `$ref` chain longer than this is pathological rather than merely nested.
MAX_REF_HOPS = 10


class ProbeError(RuntimeError):
    """The server could not be started, or did not answer in time."""


def _argument_type(schema: dict[str, Any], root: dict[str, Any] | None = None) -> str | None:
    """A single readable type name. JSON Schema can express a union (`anyOf`, or a
    list of types); those are joined so a narrowing is still visible as a change."""
    raw = schema.get("type")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "|".join(sorted(str(t) for t in raw))
    any_of = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(any_of, list):
        parts = set()
        for branch in any_of:
            if not isinstance(branch, dict):
                continue
            # `Filters | None` is spelled anyOf[$ref, null]; resolve the ref so the
            # union reads `null|object` rather than losing half of itself
            if "$ref" in branch and root is not None:
                target = _lookup_ref(str(branch["$ref"]), root)
                branch = target if isinstance(target, dict) else branch
            if branch.get("type"):
                parts.add(str(branch["type"]))
        # `anyOf: [string, null]` is how an optional string is usually spelled
        if parts:
            return "|".join(sorted(parts))
    return None


def _lookup_ref(ref: str, root: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a JSON pointer into this same document (`#/$defs/Filters`).

    An external `$ref` — anything not a local pointer — is deliberately not resolved:
    fetching it would make probing non-deterministic and network-dependent, and
    guessing at it would be worse. It gets reported instead.
    """
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None


def _resolve(
    schema: dict[str, Any],
    root: dict[str, Any],
    notes: list[str],
    path: str,
    seen: tuple[str, ...],
) -> tuple[dict[str, Any], tuple[str, ...]] | None:
    """Follow a `$ref` to the schema it points at.

    Returns None when the ref cannot or must not be followed — unresolvable, or
    already expanded on this branch (a self-referential model). Both cases append a
    note: a correctness tool that quietly records less than it claims is worse than
    one that says what it could not see.
    """
    hops = 0
    while "$ref" in schema:
        ref = str(schema["$ref"])
        where = path or "(root)"
        if ref in seen:
            notes.append(f"{where}: {ref} refers to itself; fields below here are not recorded")
            return None
        if hops >= MAX_REF_HOPS:
            notes.append(f"{where}: $ref chain deeper than {MAX_REF_HOPS}; not recorded")
            return None
        target = _lookup_ref(ref, root)
        if target is None:
            notes.append(f"{where}: could not resolve $ref {ref}; its fields are not recorded")
            return None
        seen = (*seen, ref)
        schema = target
        hops += 1
    return schema, seen


def _object_of(
    schema: dict[str, Any],
    root: dict[str, Any],
    notes: list[str],
    path: str,
    seen: tuple[str, ...],
) -> tuple[dict[str, Any], tuple[str, ...]] | None:
    """The object shape this schema describes, if it describes exactly one.

    `allOf` is a union of its branches, so its properties are merged. `anyOf`/`oneOf`
    with a single object branch is the ordinary `Model | None`, so that branch is
    used. More than one object branch means which fields apply depends on the value
    at runtime — that is not knowable from the schema, so it is reported rather than
    guessed at.
    """
    if isinstance(schema.get("properties"), dict):
        return schema, seen

    for key in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(key)
        if not isinstance(branches, list):
            continue
        found: list[tuple[dict[str, Any], tuple[str, ...]]] = []
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            resolved = _resolve(branch, root, notes, path, seen)
            if resolved is None:
                continue
            candidate, stack = resolved
            if isinstance(candidate.get("properties"), dict):
                found.append((candidate, stack))
        if not found:
            continue
        if key == "allOf":
            merged: dict[str, Any] = {}
            required: list[str] = []
            stack = seen
            for candidate, candidate_stack in found:
                merged.update(candidate["properties"])
                required.extend(str(r) for r in candidate.get("required") or [])
                stack = candidate_stack
            return {"properties": merged, "required": required}, stack
        if len(found) == 1:
            return found[0]
        notes.append(
            f"{path or '(root)'}: {key} has {len(found)} object branches, so which fields "
            "apply depends on the value; nested fields are not recorded"
        )
        return None
    return None


def _collect(
    shape: dict[str, Any],
    root: dict[str, Any],
    notes: list[str],
    prefix: str,
    depth: int,
    seen: tuple[str, ...],
) -> list[Argument]:
    """Flatten one object schema into arguments, descending into nested objects.

    Nested fields get dotted names (`filters.city`) and array elements get brackets
    (`tags[].name`). A flat, sorted list of leaf names diffs cleanly in a pull
    request, and each leaf is classified on its own — which is the point: renaming a
    field inside a nested model breaks a caller exactly as a top-level rename does.
    """
    properties = shape.get("properties")
    if not isinstance(properties, dict):
        return []
    required = {str(r) for r in shape.get("required") or []}
    out: list[Argument] = []

    for raw_name, raw_schema in properties.items():
        name = str(raw_name)
        path = f"{prefix}{name}"
        declared = raw_schema if isinstance(raw_schema, dict) else {}

        resolved = _resolve(declared, root, notes, path, seen)
        inner, stack = resolved if resolved is not None else ({}, seen)
        enum = declared.get("enum") or inner.get("enum")

        # the field itself is always recorded, even when we cannot see inside it
        out.append(
            Argument(
                name=path,
                type=_argument_type(declared, root) or _argument_type(inner, root),
                required=name in required,
                description=str(declared.get("description") or inner.get("description") or ""),
                enum=tuple(str(e) for e in enum) if isinstance(enum, list) else None,
            )
        )
        if resolved is None:
            continue

        # then descend: into the object itself, or into the element type of a list
        target: tuple[dict[str, Any], tuple[str, ...]] | None = None
        suffix = "."
        nested = _object_of(inner, root, notes, path, stack)
        if nested is not None:
            target = nested
        elif isinstance(inner.get("items"), dict):
            items = _resolve(inner["items"], root, notes, f"{path}[]", stack)
            if items is not None:
                element = _object_of(items[0], root, notes, f"{path}[]", items[1])
                if element is not None:
                    target, suffix = element, "[]."
        if target is None:
            continue
        if depth >= MAX_NESTING:
            notes.append(
                f"{path}: nested deeper than {MAX_NESTING} levels; fields below here "
                "are not recorded"
            )
            continue
        out.extend(_collect(target[0], root, notes, f"{path}{suffix}", depth + 1, target[1]))

    return out


def _fields(schema: dict[str, Any], notes: list[str] | None = None) -> tuple[Argument, ...]:
    """Reduce a JSON Schema object to its named fields. Used for both the input
    arguments and the output shape — the structure is identical; only how a change
    to it is judged differs (see compare.py)."""
    if notes is None:
        notes = []
    if not isinstance(schema, dict):
        return ()
    resolved = _resolve(schema, schema, notes, "", ())
    if resolved is None:
        return ()
    shape = _object_of(resolved[0], schema, notes, "", resolved[1])
    if shape is None:
        return ()
    fields = _collect(shape[0], schema, notes, "", 0, shape[1])
    return tuple(sorted(fields, key=lambda a: a.name))


def _behaviour(tool: Any) -> Behaviour:
    """The `annotations` hints and task support a server advertises for a tool.

    These are promises a caller acts on before reading a schema — auto-approving a
    read-only tool, retrying an idempotent one, confirming a destructive one — so a
    hint that reverses or disappears changes what is safe to do while every argument
    stays identical. Both SDK spellings are read, as everywhere else here.
    """
    annotations = _first_attr(tool, "annotations")
    execution = _first_attr(tool, "execution")

    def hint(*names: str) -> bool | None:
        if annotations is None:
            return None
        value = _first_attr(annotations, *names)
        return bool(value) if isinstance(value, bool) else None

    support = _first_attr(execution, "taskSupport", "task_support") if execution else None
    return Behaviour(
        read_only=hint("readOnlyHint", "read_only_hint"),
        destructive=hint("destructiveHint", "destructive_hint"),
        idempotent=hint("idempotentHint", "idempotent_hint"),
        open_world=hint("openWorldHint", "open_world_hint"),
        task_support=str(support) if support is not None else None,
    )


def surface_from_schema(
    name: str,
    description: str,
    schema: dict[str, Any],
    output_schema: dict[str, Any] | None = None,
    notes: list[str] | None = None,
    title: str = "",
    behaviour: Behaviour | None = None,
) -> ToolContract:
    """Reduce one tool's advertised input and output JSON Schemas to its contract.

    `notes` collects anything the schema described but the contract could not record
    — an unresolvable `$ref`, a self-referential model, nesting past the limit. The
    caller surfaces them; they are never stored, so the contract file stays stable.
    """
    return ToolContract(
        name=name,
        description=description or "",
        arguments=_fields(schema, notes),
        output=_fields(output_schema or {}, notes),
        title=title or "",
        behaviour=behaviour or Behaviour(),
    )


def _first_attr(obj: object, *names: str) -> Any:
    """Read whichever of these attributes exists.

    The MCP Python SDK renamed fields between releases — `inputSchema` became
    `input_schema`, `serverInfo` became `server_info` — so a tool that inspects
    servers has to speak both, or it breaks on half the ecosystem. (Which is, more or
    less, the argument for this project.)
    """
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _error_code(exc: BaseException) -> int | None:
    """The JSON-RPC code behind an SDK error, across both majors: 2.x renamed
    `McpError` to `MCPError` and puts the code on the exception, 1.x wraps it in an
    `ErrorData`. Reading both is the same tax the field renames charge elsewhere."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    code = getattr(getattr(exc, "error", None), "code", None)
    return code if isinstance(code, int) else None


def _cursor_kwargs(call: Any, cursor: str | None) -> dict[str, Any]:
    """How this SDK wants a cursor passed.

    1.20 introduced the `params=PaginatedRequestParams(...)` form; before that it was
    a positional `cursor`. Both are still in the wild, so both are spoken — the same
    tax `_first_attr` pays for the field renames. The first request carries no cursor
    at all, which every version accepts.
    """
    if cursor is None:
        return {}
    try:
        takes_params = "params" in inspect.signature(call).parameters
    except (TypeError, ValueError):  # pragma: no cover - a callable without a signature
        takes_params = True
    if takes_params and PaginatedRequestParams is not None:
        return {"params": PaginatedRequestParams(cursor=cursor)}
    return {"cursor": cursor}


async def _all_pages(call: Any, attr: str, notes: list[str], what: str) -> list[Any]:
    """Every page of a listing, not just the first.

    `tools/list` and its siblings are paginated and the SDK does not follow the cursor
    for you. Reading a single page records a partial surface — and a tool that merely
    sat on page two would read as *removed* the next time anyone checked.

    A server that doesn't offer the capability at all answers method-not-found, and an
    empty surface is the correct reading of that. Any *other* error is reported as a
    note rather than swallowed: "the call failed" and "there are none" are different
    facts, and only one of them is safe to write into a contract.
    """
    items: list[Any] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        try:
            result = await call(**_cursor_kwargs(call, cursor))
        except Exception as exc:  # noqa: BLE001 - the reason is what we classify on
            if _error_code(exc) != METHOD_NOT_FOUND:
                notes.append(
                    f"{what}: could not be listed ({type(exc).__name__}: {exc}); "
                    "recorded as empty"
                )
            return items
        items.extend(getattr(result, attr, None) or [])
        cursor = _first_attr(result, "nextCursor", "next_cursor")
        if not cursor:
            return items
    notes.append(f"{what}: stopped after {MAX_PAGES} pages; the server kept paginating")
    return items


async def _list_resources(session: ClientSession, notes: list[str]) -> list[str]:
    out = []
    for item in await _all_pages(session.list_resources, "resources", notes, "resources"):
        uri = getattr(item, "uri", None)
        if uri is not None:
            out.append(str(uri))
    return out


async def _list_prompts(session: ClientSession, notes: list[str]) -> list[PromptContract]:
    """Prompts with their arguments. Like tools, a prompt losing an argument (or
    gaining a required one) breaks a caller, so the arguments are part of the contract."""
    out = []
    for prompt in await _all_pages(session.list_prompts, "prompts", notes, "prompts"):
        args = tuple(
            Argument(
                name=str(a.name),
                required=bool(getattr(a, "required", False)),
                description=str(getattr(a, "description", "") or ""),
            )
            for a in (getattr(prompt, "arguments", None) or [])
        )
        out.append(PromptContract(name=str(prompt.name), arguments=args))
    return out


async def _probe(command: str, args: list[str], env: dict[str, str] | None) -> Contract:
    params = StdioServerParameters(command=command, args=args, env=env)
    notes: list[str] = []
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        listed = await _all_pages(session.list_tools, "tools", notes, "tools")
        # resources break a caller if dropped; prompts also break if an argument goes
        resources = await _list_resources(session, notes)
        prompts = await _list_prompts(session, notes)

    info = _first_attr(init, "serverInfo", "server_info")
    tools = []
    for t in listed:
        # a note names the field, so prefix it with the tool it belongs to
        before = len(notes)
        tools.append(
            surface_from_schema(
                t.name,
                t.description or "",
                dict(_first_attr(t, "inputSchema", "input_schema") or {}),
                dict(_first_attr(t, "outputSchema", "output_schema") or {}),
                notes,
                str(_first_attr(t, "title") or ""),
                _behaviour(t),
            )
        )
        notes[before:] = [f"{t.name}: {n}" for n in notes[before:]]

    return Contract(
        tools=tools,
        resources=resources,
        prompts=prompts,
        server_name=getattr(info, "name", "") or "",
        server_version=getattr(info, "version", "") or "",
        command=shlex.join([command, *args]),
        unrecorded=notes,
    )


def probe(
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Contract:
    """Start the server, read its tool surface, shut it down.

    Raises ProbeError with the underlying reason — a missing executable and a server
    that hangs are both ordinary mistakes, and both deserve a sentence rather than a
    traceback.
    """
    try:
        return asyncio.run(asyncio.wait_for(_probe(command, list(args or []), env), timeout))
    except asyncio.TimeoutError as exc:
        raise ProbeError(
            f"{command} did not answer within {timeout:g}s. "
            "Is it an MCP server that speaks stdio?"
        ) from exc
    except FileNotFoundError as exc:
        raise ProbeError(f"could not run {command!r}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surface the cause, never a traceback
        raise ProbeError(f"could not probe {command!r}: {type(exc).__name__}: {exc}") from exc
