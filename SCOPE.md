# Agent Memory — v1 Scope

**One line:** Portable, local-first persistent memory for any AI agent — stored as plain markdown files a human can read and edit, served to agents over MCP.

**The problem:** Every agent session starts with amnesia. Switch agents, models, or tools and the memory is gone or trapped in one vendor's black box. Every agent builder rebuilds memory from scratch.

## Principles
1. **Files, not a database.** Memory is markdown in a folder the user owns. Open it, read it, edit it, back it up, put it in git.
2. **Agent-agnostic.** Any MCP client (Claude Code, Cursor, Codex, custom agents) connects to the same store. Swap the agent, keep the memory.
3. **Local-first.** No cloud, no account, no API key, $0 to run. The server is a single Python file using only the standard library.
4. **Honest retrieval.** Search returns the exact lines that matched, with file + line references — the agent (and the human) can verify where a "memory" came from.

## v1 — in scope
- Memory store scaffolding (`init`): `MEMORY.md` (durable facts), `logs/YYYY-MM-DD.md` (daily logs), `topics/<topic>.md` (per-topic notes).
- MCP server over stdio with 5 tools: `memory_search`, `memory_get`, `memory_save`, `memory_log`, `memory_status`.
- The same operations as a plain CLI, so it works (and is testable) without any MCP client.
- Keyword search with ranked snippets and file/line citations.
- Path safety: reads/writes can never escape the store directory.

## v0.3 — Behavior Memory (added 2026-10-14)
The differentiator: competitors store facts; we also store behavior.
- `LESSONS.md` + `memory_learn`: mistakes and the rule they taught ("scar tissue"). Lessons outrank facts in search and lead every brief.
- `INTENTIONS.md` + `memory_intend`: prospective memory — WHEN a trigger happens, DO an action — surfaced by situation in the brief, not by search.
- `memory_brief`: the session-start pack (warnings → triggered intentions → core facts → recent activity), all cited.
- Deliberately still no embeddings, no automatic capture, no cloud: behavior entries are curated exactly like facts.

## v1 — deliberately NOT in scope
- No embeddings / vector search (keyword + citations first; semantics later if real use demands it).
- No cloud sync, no multi-user permissions, no GUI.
- No automatic conversation capture — the agent (or human) decides what is worth saving. Memory quality is a curation problem, not a hoarding problem.
- No memory "brains" per vendor — one store, every agent.

## Success test for v1
Save a fact in one process. Kill it. In a brand-new process — ideally a *different agent client* — ask for it and get it back with a citation. That demo is the product.
