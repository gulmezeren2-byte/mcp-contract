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


def surface_from_schema(name: str, description: str, schema: dict[str, Any]) -> ToolContract:
    """Reduce one tool's advertised JSON Schema to its contract."""
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    arguments = []
    for arg_name, arg_schema in properties.items():
        if not isinstance(arg_schema, dict):
            arg_schema = {}
        enum = arg_schema.get("enum")
        arguments.append(
            Argument(
                name=str(arg_name),
                type=_argument_type(arg_schema),
                required=arg_name in required,
                description=str(arg_schema.get("description") or ""),
                enum=tuple(str(e) for e in enum) if isinstance(enum, list) else None,
            )
        )
    return ToolContract(
        name=name,
        description=description or "",
        arguments=tuple(sorted(arguments, key=lambda a: a.name)),
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


async def _probe(command: str, args: list[str], env: dict[str, str] | None) -> Contract:
    params = StdioServerParameters(command=command, args=args, env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        listed = await session.list_tools()

    info = _first_attr(init, "serverInfo", "server_info")
    tools = [
        surface_from_schema(
            t.name,
            t.description or "",
            dict(_first_attr(t, "inputSchema", "input_schema") or {}),
        )
        for t in listed.tools
    ]
    return Contract(
        tools=tools,
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
