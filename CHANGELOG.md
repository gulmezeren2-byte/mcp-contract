# Changelog

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
