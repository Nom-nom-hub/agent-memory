# Agent Memory

**Portable, local-first persistent memory for AI agents.**

Every agent session starts with amnesia. Switch agents, models, or tools and
the memory is gone — or trapped inside one vendor's black box.

Agent Memory fixes that with the simplest possible design:

- **Files, not a database.** Memory is plain markdown in a folder you own.
  Open it, read it, edit it, back it up, put it in git.
- **Agent-agnostic.** Any MCP client connects to the same store.
  Swap the agent, keep the memory.
- **Local-first.** No cloud, no account, no API key, $0 to run.
  One Python file, standard library only.
- **Honest retrieval.** Search returns the exact matching lines with
  file + line citations, so a "memory" can always be verified.

## Quickstart (no agent required)

```bash
python3 agent_memory.py init
python3 agent_memory.py save "The deploy target is Fly.io, region iad"
python3 agent_memory.py log "Migrated the staging database"
# ...new terminal, new day, new process:
python3 agent_memory.py search "where do we deploy"
```

Or run the 20-second demo — a fact saved in one process, recalled by a
brand-new one:

```bash
./demo.sh
```

## Connect an agent (MCP)

The server speaks MCP over stdio: `python3 agent_memory.py serve`

**Claude Code**

```bash
claude mcp add agent-memory -- python3 /path/to/agent-memory/agent_memory.py serve
```

**Cursor / generic MCP clients** (`mcp.json`)

```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "python3",
      "args": ["/path/to/agent-memory/agent_memory.py", "serve"],
      "env": { "AGENT_MEMORY_DIR": "/path/to/your/memory-store" }
    }
  }
}
```

Point two different agents at the same store directory and they share one
memory. That's the whole trick.

## Tools

| Tool | What it does |
|---|---|
| `memory_search` | Ranked keyword search over all memory files, with file + line citations |
| `memory_get` | Read a memory file (or a line window of it) |
| `memory_save` | Save a durable fact to `MEMORY.md`, or to `topics/<topic>.md` |
| `memory_log` | Append a timestamped entry to today's daily log |
| `memory_status` | Store location, file list, and size |

Every tool is also a CLI subcommand with the same name minus the prefix
(`search`, `get`, `save`, `log`, `status`).

## Store layout

```
~/.agent-memory/        (override with --store or $AGENT_MEMORY_DIR)
├── MEMORY.md           durable facts
├── logs/
│   └── 2026-10-14.md   daily logs, timestamped entries
└── topics/
    └── <topic>.md      per-topic notes
```

Reads and writes are confined to the store directory — path traversal is
refused, and topic names are slugified before they touch the filesystem.

## Tests

```bash
python3 -m unittest discover -s tests   # 9 tests, incl. a live MCP stdio round-trip
```

## What v1 deliberately is not

No embeddings or vector search. No cloud sync. No GUI. No automatic
conversation capture — the agent (or you) decides what's worth saving.
Memory quality is a curation problem, not a hoarding problem.
See [SCOPE.md](SCOPE.md) for the full reasoning.

## Status

v0.1.0 — working local build. Not yet published (no npm/PyPI/GitHub release).
