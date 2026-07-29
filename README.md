# mcp-contract

**Contract testing for MCP servers — catch a breaking change before your users do.**

Your MCP server's tool surface is a promise: these tools exist, they take these arguments, these ones are required. Agents are written against that promise. Rename an argument and every one of them breaks — silently, in somebody else's pipeline, with no test of yours turning red.

`mcp-contract` records the promise, and holds you to it.

```
$ mcp-contract check -- my-mcp-server

breaking (2)
  tool-removed  export_csv
      the tool is gone; an agent that depends on it fails
  argument-now-required  parse_catalog → pages
      was optional, now required; every call that omitted it breaks

routing (1)
  tool-description-changed  diff
      no call breaks, but the agent routes on this text — it may stop choosing
      this tool, or start choosing it for the wrong task

3 tool(s) · 2 breaking · 1 routing
Breaking: agents built against the recorded contract will fail.
```

## Install

```
uvx mcp-contract          # run without installing
pip install mcp-contract  # or install it
```

## Use

```
mcp-contract snapshot -- my-mcp-server    # record the surface; commit the file
mcp-contract check    -- my-mcp-server    # non-zero when a change breaks callers
mcp-contract show     -- my-mcp-server    # just look, record nothing
```

The server command goes after `--`, so its own flags are never mistaken for ours. It's started the way your users start it — as a subprocess over stdio — and asked for `tools/list`. **No tool is ever called**, so checking is side-effect free.

Commit `mcp-contract.json`. Then the diff a reviewer sees in a pull request *is* the change in the promise.

```yaml
- run: uvx mcp-contract check -- my-mcp-server
```

## The three kinds of change

Every diff is noise unless you say who it hurts. Changes are classified by what they do to a caller already in the wild:

| | |
|---|---|
| **breaking** | An existing valid call stops working: a tool disappears, an argument is removed, an optional argument becomes required, a type narrows, an accepted enum value is dropped. **Exits non-zero.** |
| **additive** | New surface nobody was using yet: a new tool, a new optional argument, a widened type, a new enum value. Reported, never fatal. |
| **routing** | The schema is untouched but a **description** changed. See below. |
| **cosmetic** | The server's version string. Noise. |

### Why "routing" is its own class

An agent doesn't read your JSON Schema to decide *whether* to call a tool — it reads the description. Reword it and no call breaks, no schema differs, every contract test in the ordinary sense passes... and the agent may quietly stop choosing that tool, or start choosing it for the wrong task. That's a real behavioural change a schema diff cannot see, so it gets named rather than buried. It doesn't fail the build by default; `--strict` is how you say it should.

## Honest about the edges

- It compares the **input** surface and the descriptions. Output schemas aren't diffed yet.
- It reads what the server *advertises*. Whether a tool still behaves correctly is a different question, and this doesn't answer it.
- Type comparison is structural: `string` → `string|null` is widening (safe), the reverse is narrowing (breaking). Each argument is compared at the top level of its schema.
- Re-snapshotting is how you accept a change deliberately. Nothing is rewritten behind your back.
- It speaks both MCP Python SDK spellings (`inputSchema` and `input_schema`), because the SDK renamed them and servers in the wild use both — which is, more or less, the argument for this project.

## License

MIT
