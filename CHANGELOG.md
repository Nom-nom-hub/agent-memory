# Changelog

## 0.2.1 — 2026-10-14

Fixes from the first external field test (issues #1–#3, reported by an agent
that actually ran the tool on Windows — thank you):

- **#1 UTF-8 transport.** The MCP stdio transport now reconfigures
  stdin/stdout to UTF-8 explicitly. On Windows the locale codepage (cp1252)
  was silently double-encoding non-ASCII memory text (`café` → `cafÃ©`).
- **#2 The server loop cannot be killed by one bad message.** Non-object
  JSON is skipped, JSON-RPC batch arrays are answered, non-string methods
  get a clean `-32600`, handler exceptions become `-32603`, and
  notification-form requests are never replied to — nor executed
  (a notification-form `tools/call` previously mutated the store).
- **#3.1 Containment through links.** Files reached through a symlink or
  junction inside the store are no longer searched, read, or rewritten —
  `memory_forget` could previously delete lines from files *outside* the
  store. `MEMORY.md` writes now go through the same checked path helper.
- **#3.2 Topic injection closed.** The topic heading written into a new
  topic file is single-line normalized, so a newline in a topic can no
  longer inject fabricated, dated "facts" into the store.
- **#3.3 POSIX paths everywhere.** All tools return `topics/x.md`-style
  paths (previously Windows search/status/forget returned backslashes,
  which also failed the test suite there). `memory_get` returns the
  normalized path instead of echoing raw input.
- **#3.4 Smaller findings.** Non-Latin topics get stable hash filenames
  instead of all merging into `notes.md`; tool argument coercion is
  tolerant and clamped (no leaked `int()` errors, no negative-limit
  surprises); `memory_recent` only reads date-named log files; search
  matches whole words (`cat` no longer hits `concatenate`) and
  stopword-only queries fall back to phrase matching; an unusable store
  path now produces an actionable error instead of a traceback.
- Test suite: 12 → 25 tests, with a regression test for every item above.

## 0.2.0 — 2026-10-14

- Real packaging: `pip install` / `uv tool install` provides the
  `agent-memory` command.
- New tools: `memory_forget` (correct/delete a memory, returns exactly
  what was removed) and `memory_recent` (newest daily-log entries).
- README: uvx-first MCP setup (no clone needed).

## 0.1.0 — 2026-10-14

- First release: MCP stdio server + CLI over a plain-markdown memory
  store. Tools: `memory_search`, `memory_get`, `memory_save`,
  `memory_log`, `memory_status`.
