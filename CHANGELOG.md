# Changelog

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
