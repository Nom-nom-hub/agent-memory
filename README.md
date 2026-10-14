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

**Easiest — uvx, no clone, no install** (verified end-to-end):

```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Nom-nom-hub/agent-memory", "agent-memory", "serve"],
      "env": { "AGENT_MEMORY_DIR": "/path/to/your/memory-store" }
    }
  }
}
```

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

## Behavior Memory — the part nobody else ships

Every other agent-memory product stores **facts**: what the agent knows.
Agent Memory also stores **behavior**: what the agent has learned to *do*.

- **Lessons** (`memory_learn` → `LESSONS.md`) — scar tissue. A mistake, what
  went wrong, and the rule it taught. Lessons **outrank facts in search**
  (×3) and lead every brief, so the next agent — *any* agent — hits the
  warning before repeating the mistake, not after. Correct an agent once;
  every agent you ever open has been corrected.
- **Intentions** (`memory_intend` → `INTENTIONS.md`) — prospective memory.
  `WHEN <trigger> → DO <action>`. Intentions aren't found by searching;
  they **surface automatically** in the brief when the session context
  matches their trigger. Memory for the future, retrieved by situation.
- **Brief** (`memory_brief`) — the session-start ritual in one call:
  warnings first, triggered intentions, core facts, recent activity —
  each line with its file:line citation.

> Mem0 remembers what you told it. Agent Memory remembers what you taught it.

## Tools

| Tool | What it does |
|---|---|
| `memory_search` | Ranked keyword search over all memory files, with file + line citations; lessons boosted, every hit tagged by kind (fact / lesson / intention / log / topic) |
| `memory_get` | Read a memory file (or a line window of it) |
| `memory_save` | Save a durable fact to `MEMORY.md`, or to `topics/<topic>.md` |
| `memory_log` | Append a timestamped entry to today's daily log |
| `memory_forget` | Remove memory entries containing a text — correct or delete a wrong memory; returns exactly what was removed |
| `memory_recent` | Most recent daily-log entries, newest first |
| `memory_status` | Store location, file list, size, lesson/intention counts |
| `memory_learn` | Record a lesson: situation + what went wrong + the rule (Behavior Memory) |
| `memory_intend` | Record an intention: WHEN a trigger happens, DO an action (Behavior Memory) |
| `memory_brief` | Session-start pack: warnings, triggered intentions, core facts, recent activity — cited |

Every tool is also a CLI subcommand with the same name minus the prefix
(`search`, `get`, `save`, `log`, `forget`, `recent`, `status`, `learn`,
`intend`, `brief`).

## Install as a command

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv tool install --from git+https://github.com/Nom-nom-hub/agent-memory agent-memory-mcp
agent-memory --version
agent-memory init
```

Or with pip:

```bash
pip install git+https://github.com/Nom-nom-hub/agent-memory
```

## Store layout

```
~/.agent-memory/        (override with --store or $AGENT_MEMORY_DIR)
├── MEMORY.md           durable facts
├── LESSONS.md          Behavior Memory: mistakes + the rule each taught
├── INTENTIONS.md       Behavior Memory: WHEN trigger → DO action
├── logs/
│   └── 2026-10-14.md   daily logs, timestamped entries
└── topics/
    └── <topic>.md      per-topic notes
```

Reads and writes are confined to the store directory — path traversal is
refused, and topic names are slugified before they touch the filesystem.

## Tests

```bash
python3 -m unittest discover -s tests   # 42 tests, incl. live MCP round-trips, regressions for issues #1–#3, both post-0.2.1 server-killers, and the Behavior Memory suite
```

## What v1 deliberately is not

No embeddings or vector search. No cloud sync. No GUI. No automatic
conversation capture — the agent (or you) decides what's worth saving.
Memory quality is a curation problem, not a hoarding problem.
See [SCOPE.md](SCOPE.md) for the full reasoning.

## Status

v0.3.0 — public repo: https://github.com/Nom-nom-hub/agent-memory — see [CHANGELOG.md](CHANGELOG.md)
Not yet on PyPI; install from GitHub (above) for now.
