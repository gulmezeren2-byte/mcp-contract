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
import shlex
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_contract.model import Argument, Contract, ToolContract

DEFAULT_TIMEOUT = 60.0


class ProbeError(RuntimeError):
    """The server could not be started, or did not answer in time."""


def _argument_type(schema: dict[str, Any]) -> str | None:
    """A single readable type name. JSON Schema can express a union (`anyOf`, or a
    list of types); those are joined so a narrowing is still visible as a change."""
    raw = schema.get("type")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "|".join(sorted(str(t) for t in raw))
    any_of = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(any_of, list):
        parts = sorted(
            {str(s.get("type")) for s in any_of if isinstance(s, dict) and s.get("type")}
        )
        # `anyOf: [string, null]` is how an optional string is usually spelled
        if parts:
            return "|".join(parts)
    return None


def _fields(schema: dict[str, Any]) -> tuple[Argument, ...]:
    """Reduce a JSON Schema object to its named fields. Used for both the input
    arguments and the output shape — the structure is identical; only how a change
    to it is judged differs (see compare.py)."""
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields = []
    for field_name, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            field_schema = {}
        enum = field_schema.get("enum")
        fields.append(
            Argument(
                name=str(field_name),
                type=_argument_type(field_schema),
                required=field_name in required,
                description=str(field_schema.get("description") or ""),
                enum=tuple(str(e) for e in enum) if isinstance(enum, list) else None,
            )
        )
    return tuple(sorted(fields, key=lambda a: a.name))


def surface_from_schema(
    name: str,
    description: str,
    schema: dict[str, Any],
    output_schema: dict[str, Any] | None = None,
) -> ToolContract:
    """Reduce one tool's advertised input and output JSON Schemas to its contract."""
    return ToolContract(
        name=name,
        description=description or "",
        arguments=_fields(schema),
        output=_fields(output_schema or {}),
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


async def _list_names(coro: Any, attr: str, key: str) -> list[str]:
    """Best-effort names from list_resources / list_prompts. A server that doesn't
    support the capability raises; that's an empty surface, not an error."""
    try:
        result = await coro()
    except Exception:  # noqa: BLE001 - unsupported capability is not a failure
        return []
    items = getattr(result, attr, None) or []
    out = []
    for item in items:
        value = getattr(item, key, None)
        if value is not None:
            out.append(str(value))
    return out


async def _probe(command: str, args: list[str], env: dict[str, str] | None) -> Contract:
    params = StdioServerParameters(command=command, args=args, env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        listed = await session.list_tools()
        # resources are keyed by URI, prompts by name — both break a caller if dropped
        resources = await _list_names(session.list_resources, "resources", "uri")
        prompts = await _list_names(session.list_prompts, "prompts", "name")

    info = _first_attr(init, "serverInfo", "server_info")
    tools = [
        surface_from_schema(
            t.name,
            t.description or "",
            dict(_first_attr(t, "inputSchema", "input_schema") or {}),
            dict(_first_attr(t, "outputSchema", "output_schema") or {}),
        )
        for t in listed.tools
    ]
    return Contract(
        tools=tools,
        resources=resources,
        prompts=prompts,
        server_name=getattr(info, "name", "") or "",
        server_version=getattr(info, "version", "") or "",
        command=shlex.join([command, *args]),
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
