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

## Nested arguments

A tool that takes a model rather than a handful of scalars advertises a `$ref`:

```json
{ "properties": { "filters": { "$ref": "#/$defs/Filters" } },
  "$defs": { "Filters": { "properties": { "city": {"type": "string"} }, "required": ["city"] } } }
```

That's what any Pydantic model compiles to, so it's the normal shape, not an exotic one. The fields a caller actually has to get right live behind the reference — so they're followed, and recorded with dotted names:

```
filters          object    required
filters.city     string    required
filters.year     integer   required
limit            integer
```

Rename `city` and you get `argument-removed filters.city` — breaking, exactly as a top-level rename is. Lists of models get bracket notation (`tags[].name`). Nested required-ness is *relative to its parent*: `filters.city` being required means a caller who supplies `filters` must include `city`, whatever `filters`' own required-ness is.

Resolution is bounded and never quiet about it. Nesting stops at four levels, a model that refers to itself stops where it loops, an external `$ref` is not fetched, and an `anyOf` with two object branches isn't guessed at — each of those prints under **not recorded** rather than being dropped in silence.

Contract files carry a `format` number. One recorded before nested fields were tracked (mcp-contract ≤ 0.3.0) never promised anything about them, so `check` holds itself to what that file actually claimed and tells you to re-snapshot — upgrading this tool never reports a breaking change on a server that didn't change.

## Honest about the edges

- It compares tools (input arguments — nested ones included — **and** output fields), prompts (presence **and** their arguments), and the presence of resources.
- Output schemas are only as detailed as the server advertises. A server that returns an untyped object (`additionalProperties: true`, common with dict-returning FastMCP tools) has no output fields to diff — that's correct, not a miss.
- It reads what the server *advertises*. Whether a tool still behaves correctly is a different question, and this doesn't answer it.
- Type comparison is structural: `string` → `string|null` is widening (safe), the reverse is narrowing (breaking).
- Per-call metadata is deliberately excluded. The `ttlMs` and `cacheScope` fields the 2026-07-28 spec requires on list responses are cache hints that can differ between two probes of an unchanged server; recording them would make every `check` a diff about nothing.
- Listings are paginated and the SDK doesn't follow the cursor for you, so every page is read. A partial read would be worse than useless here: a tool that merely sat on page two would come back as *removed*.
- A server that doesn't offer prompts or resources answers method-not-found, and recording nothing is the right reading of that. Any **other** failure of a listing is printed rather than read as "there are none" — those are different facts, and only one of them is safe to write into a contract.
- Re-snapshotting is how you accept a change deliberately. Nothing is rewritten behind your back.
- It speaks both MCP Python SDK spellings (`inputSchema` and `input_schema`), because the SDK renamed them and servers in the wild use both — which is, more or less, the argument for this project.

## Related

- **[claude-skills-doctor](https://github.com/gulmezeren2-byte/claude-skills-doctor)** — the same idea one layer up. `mcp-contract` watches the tools an agent *calls*; `claude-skills-doctor` watches the skills it can *reach* — the silent 15,000-char discovery budget, and descriptions that collide so Claude picks the wrong one. Both treat the text an agent routes on as a contract worth testing.

More tools by [Eren Gülmez](https://github.com/gulmezeren2-byte?tab=repositories).

## License

MIT
