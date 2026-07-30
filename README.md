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
| **breaking** | An existing valid call stops working, or a promised result changes out from under a caller: a tool, argument, resource or prompt disappears; an argument is removed; an optional argument becomes required; an input type narrows; an output field is removed, becomes optional, or *widens* (the caller may now receive a value it didn't handle). **Exits non-zero.** |
| **additive** | New surface nobody was using yet: a new tool, a new optional argument, a widened *input* type, a new *output* field. Reported, never fatal. |
| **routing** | The schema is untouched but a **description** changed. See below. |
| **cosmetic** | The server's version string. Noise. |

Note the mirror: for an **input** argument, widening the accepted type is safe and narrowing it breaks callers; for an **output** field, it's the reverse — widening what you might return can break a caller that only handled the narrower shape. mcp-contract judges each from the caller's side.

### Why "routing" is its own class

An agent doesn't read your JSON Schema to decide *whether* to call a tool — it reads the description. Reword it and no call breaks, no schema differs, every contract test in the ordinary sense passes... and the agent may quietly stop choosing that tool, or start choosing it for the wrong task. That's a real behavioural change a schema diff cannot see, so it gets named rather than buried. It doesn't fail the build by default; `--strict` is how you say it should.

## Honest about the edges

- It compares tools (input arguments **and** output fields), plus the presence of resources and prompts. Prompt *arguments* aren't diffed field-by-field yet — only whether the prompt still exists.
- Output schemas are only as detailed as the server advertises. A server that returns an untyped object (`additionalProperties: true`, common with dict-returning FastMCP tools) has no output fields to diff — that's correct, not a miss.
- It reads what the server *advertises*. Whether a tool still behaves correctly is a different question, and this doesn't answer it.
- Type comparison is structural: `string` → `string|null` is widening (safe), the reverse is narrowing (breaking). Each argument is compared at the top level of its schema.
- Re-snapshotting is how you accept a change deliberately. Nothing is rewritten behind your back.
- It speaks both MCP Python SDK spellings (`inputSchema` and `input_schema`), because the SDK renamed them and servers in the wild use both — which is, more or less, the argument for this project.

## Related

- **[claude-skills-doctor](https://github.com/gulmezeren2-byte/claude-skills-doctor)** — the same idea one layer up. `mcp-contract` watches the tools an agent *calls*; `claude-skills-doctor` watches the skills it can *reach* — the silent 15,000-char discovery budget, and descriptions that collide so Claude picks the wrong one. Both treat the text an agent routes on as a contract worth testing.

More tools by [Eren Gülmez](https://github.com/gulmezeren2-byte?tab=repositories).

## License

MIT
