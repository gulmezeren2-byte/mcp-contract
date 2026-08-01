# Changelog

## 0.6.0 — 2026-08-01

Extends the contract from what a tool *takes* to what it promises about *itself*.

- **Tool behaviour hints are now part of the contract.** A server can advertise
  `readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint`, and callers
  act on them before ever reading a schema — an agent host auto-approves a read-only
  tool, retries an idempotent one, confirms a destructive one. Flipping a hint changes
  what is safe to do with the tool **while every argument stays byte-identical**, so a
  schema diff cannot see it. Reversing a hint or withdrawing one is **breaking**;
  declaring one for the first time, or moving toward the safer value, is **additive**,
  because new information about a tool is not a change in what it was already doing.
  `execution.taskSupport` is compared the same way, and `title` — the display name a
  human or an agent picks a tool by — is **routing**.
- This is the tool-poisoning shape: a server that reads as safe at approval time and
  changes afterwards. The protocol will not solve it — the proposal to make a content
  digest mandatory on every tool
  ([SEP-1766](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/1766))
  was closed, as was tool semantic versioning (SEP-1575) — so a committed, diffable
  record of what a server *said* is the practical defence.
- Verified end-to-end against a live server whose input schema is unchanged and whose
  only difference is `readOnlyHint: true → false`: two breaking changes, named.
- **Omitted hints are resolved to their documented defaults before anything is
  judged** — `readOnlyHint` false, `destructiveHint` true, `idempotentHint` false,
  `openWorldHint` true, per `schema.ts`. An absent hint is a promise, not a silence,
  so a server that merely starts *writing out* `destructiveHint: true` has published
  nothing new and gets a cosmetic note instead of an alarm. Comparing the literal
  values would have raised a false breaking change every time a server became more
  explicit. And since the spec says `destructiveHint` and `idempotentHint` are
  meaningful "only when `readOnlyHint == false`", they are skipped for a tool that is
  read-only on both sides.
- `taskSupport` is judged by the same asymmetry: `optional` accepts callers of both
  styles, so moving *to* it is additive and moving away from it is breaking.
- No noise for servers that set none of this: an unannotated tool writes no
  `behaviour` key at all, and snapshots stay byte-stable across probes. The public
  `@modelcontextprotocol/server-memory` turns out to set `title` on every tool and
  `taskSupport: forbidden`, but no annotation hints — so the committed demo image was
  regenerated to match.


## 0.5.1 — 2026-07-31

- **Fixed: the declared SDK range was a claim, not a fact.** `pyproject.toml` said
  `mcp>=1.2`, but 0.5.0's pagination passed the cursor as
  `params=PaginatedRequestParams(...)` — a form the SDK only grew in **1.20**. On
  anything older the second page raised `TypeError`, and on 1.2 the module did not
  import at all. Every check of 0.4.0 and 0.5.0 had run against SDK 2.0.0, so the
  older client path had never once been executed.
  The cursor is now passed the way the installed SDK wants it — `params=` where that
  exists, positional `cursor=` before it — and the floor is `mcp>=1.9`, which is a
  range that has actually been run: verified end-to-end on **1.9.4, 1.16.0, 1.20.0,
  1.28.1 and 2.0.0**, each probing a live server with a nested model.

  This is the same defect the tool exists to catch, in the tool itself: a promise
  wider than what was tested.


## 0.5.0 — 2026-07-30

Two more ways the contract could have been quietly incomplete, closed. Same theme as
0.4.0: the danger in a tool like this isn't being wrong, it's being silently partial.

- **Every page of a listing is read.** `tools/list`, `prompts/list` and
  `resources/list` are paginated, and the SDK does not follow the cursor for you — a
  single call reads one page. Against a server that paginates, the recorded contract
  would have been a fraction of the surface, and a tool that merely sat on page two
  would have come back as `tool-removed` — breaking, against a server that never
  changed. The cursor is now followed to the end, bounded at 100 pages so a server
  that keeps handing out cursors stops the probe instead of hanging it.
- **"The listing failed" is no longer recorded as "there are none."** Every error
  from the optional listings was swallowed, so a prompts call that died on a bad
  connection produced the same contract as a server with no prompts — and the next
  `check` against a real server would then have reported every prompt as added, or
  worse, a genuine removal would have been invisible. Method-not-found still means an
  empty surface, correctly and quietly; any other failure is now surfaced.
- Reads the SDK's error shape across both majors — 2.x renamed `McpError` to
  `MCPError` and moved the JSON-RPC code onto the exception. Same tax the field
  renames charge, same fix.


## 0.4.0 — 2026-07-30

Fixes a silent miss: part of the surface this tool claimed to hold servers to was
never actually being recorded.

- **`$ref` is now resolved, so nested arguments are part of the contract.** A tool
  taking a Pydantic model advertises `{"$ref": "#/$defs/Filters"}` with the real
  fields under `$defs`. Earlier versions read only top-level `properties`, recorded
  the argument with no type and no inner fields, and therefore reported *"No change"*
  when a field inside the model was renamed, retyped, or made required — breaking
  changes, reported as safe. Nested fields are now recorded with dotted names
  (`filters.city`), lists of models with brackets (`tags[].name`), and `allOf` /
  `anyOf` / `oneOf` and the older `definitions` keyword are followed too. Nested
  required-ness is relative to the parent. MCP spec revision 2026-07-28 (SEP-2106)
  makes `$ref` resolution a client requirement; it was a correctness bug either way.
- **Bounded, and never a silent truncation.** Nesting stops at four levels, a
  self-referential model stops where it loops, an external `$ref` is not fetched, and
  an `anyOf` with more than one object branch is not guessed at. Every one of those
  is printed under *not recorded* — in a tool whose whole thesis is honest
  measurement, quietly recording less than it claims would be the worst defect it
  could have. `--json` carries them as `notes`; they never affect the exit code.
- **Upgrading is not a breaking change.** Contract files now carry a `format` number.
  A file recorded by ≤ 0.3.0 never asserted anything about nested fields, so `check`
  holds itself to what that file actually claimed and says to re-snapshot, instead of
  reporting the newly-visible required fields as `required-argument-added`. Without
  this, upgrading the tool would have failed the build of every user whose server
  takes a nested model, on a server that never changed.


## 0.3.0 — 2026-07-30

- **Prompt arguments are now part of the contract.** 0.2.0 tracked prompts by
  presence only; now their arguments are diffed the way tool inputs are, since a
  caller supplies them: removing a prompt argument, or making an optional one
  required, breaks an existing invocation, while a new optional argument is additive.
- The contract file's `prompts` field grows from a list of names to a list of
  `{name, arguments}`. Contracts written by 0.2.0 (bare names) still read — an
  absent `arguments` list simply means no arguments were recorded.


## 0.2.0 — 2026-07-30

Extends the contract from the input surface to the whole surface a caller depends on.

- **Output fields are now part of the contract.** A tool's result schema is captured
  and diffed — and judged from the *receiving* side, which is the mirror of an input
  argument: removing an output field, or making it optional, breaks a caller that
  reads it, and **widening** an output type is breaking (the caller may now get a value
  it never handled) while narrowing is safe. Servers that return an untyped object
  (`additionalProperties: true`) simply have nothing to diff — correct, not a miss.
- **Resources and prompts** are captured too. A server that silently drops a resource
  or a prompt breaks its callers exactly as a removed tool does, so their disappearance
  is now a breaking change.
- Closes the "output schemas aren't diffed yet" gap noted in 0.1.0.


## 0.1.0 — 2026-07-29

First public release.

- **`snapshot` / `check` / `show`** — record an MCP server's tool surface, then fail
  CI when a change would break the agents that depend on it. The server is started
  over stdio the way its users start it and asked for `tools/list`; no tool is ever
  called, so checking is side-effect free.
- **Changes are classified by who they hurt**, not by what differs in the JSON:
  *breaking* (tool or argument removed, optional argument becomes required, type
  narrowed, enum value dropped) exits non-zero; *additive* (new tool, new optional
  argument, widened type, new enum value) is reported and never fatal.
- **A `routing` class for description changes.** An agent selects a tool by reading
  its description, not its schema. Reword one and no call breaks, no schema differs,
  and the agent may still stop choosing that tool — a behavioural change no schema
  diff can see. Reported on its own; `--strict` makes it fail the build.
- The contract file is deterministic (sorted, indented, newline-terminated) so it can
  live in git and a re-snapshot of an unchanged server produces no diff.
- Speaks both MCP Python SDK spellings (`inputSchema` and `input_schema`) — the SDK
  renamed them between releases and servers in the wild use both.
- `--json` for CI, honest errors instead of tracebacks, and a UTF-8 output guard so a
  piped run on Windows doesn't die on a non-ASCII tool description.
