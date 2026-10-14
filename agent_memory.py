#!/usr/bin/env python3
"""Agent Memory — portable, local-first persistent memory for AI agents.

Memory is plain markdown files in a folder the user owns. This single file
(standard library only) serves that store two ways:

  * as an MCP server over stdio (tools: memory_search, memory_get,
    memory_save, memory_log, memory_status), and
  * as a plain CLI with the same operations.

Usage:
  python3 agent_memory.py [--store DIR] init
  python3 agent_memory.py [--store DIR] save "fact to remember" [--topic NAME]
  python3 agent_memory.py [--store DIR] search "query"
  python3 agent_memory.py [--store DIR] get MEMORY.md [--from N] [--lines N]
  python3 agent_memory.py [--store DIR] log "what happened today"
  python3 agent_memory.py [--store DIR] status
  python3 agent_memory.py [--store DIR] serve        # MCP stdio server

Store resolution order: --store flag, $AGENT_MEMORY_DIR, ~/.agent-memory
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

MEMORY_TEMPLATE = """# MEMORY.md

Durable facts this agent should remember across sessions.
Humans can edit this file directly — the agent reads the same text you do.

## Saved facts
"""

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "it",
    "that", "this", "with", "as", "by", "at", "from", "was", "are", "be",
}


# ---------------------------------------------------------------- store ----

def resolve_store(cli_value):
    if cli_value:
        return Path(cli_value).expanduser()
    env = os.environ.get("AGENT_MEMORY_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".agent-memory"


def init_store(store: Path) -> dict:
    (store / "logs").mkdir(parents=True, exist_ok=True)
    (store / "topics").mkdir(parents=True, exist_ok=True)
    mem = store / "MEMORY.md"
    created = []
    if not mem.exists():
        mem.write_text(MEMORY_TEMPLATE, encoding="utf-8")
        created.append("MEMORY.md")
    return {"store": str(store), "created": created, "ok": True}


def _safe_path(store: Path, rel: str) -> Path:
    """Resolve rel inside the store. Refuse anything that escapes it."""
    target = (store / rel).resolve()
    if store.resolve() not in target.parents and target != store.resolve():
        raise ValueError(f"path escapes the memory store: {rel!r}")
    return target


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "notes"


def _iter_md_files(store: Path):
    if not store.exists():
        return
    for path in sorted(store.rglob("*.md")):
        if path.is_file():
            yield path


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _now_time() -> str:
    return datetime.now().astimezone().strftime("%H:%M")


# ------------------------------------------------------------ operations ----

def search(store: Path, query: str, limit: int = 8) -> list:
    tokens = [t for t in re.findall(r"[a-z0-9']+", query.lower())
              if len(t) >= 2 and t not in STOPWORDS]
    if not tokens:
        return []
    phrase = query.strip().lower()
    results = []
    for path in _iter_md_files(store):
        rel = str(path.relative_to(store))
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, start=1):
            low = line.lower()
            hits = sum(low.count(t) for t in tokens)
            if hits == 0:
                continue
            score = hits
            if len(phrase) >= 4 and phrase in low:
                score += 5
            results.append({
                "file": rel,
                "line": i,
                "score": score,
                "text": line.strip()[:240],
            })
    results.sort(key=lambda r: (-r["score"], r["file"], r["line"]))
    return results[:limit]


def get_file(store: Path, rel: str, from_line: int = 1, lines: int = 200) -> dict:
    target = _safe_path(store, rel)
    if not target.is_file():
        raise FileNotFoundError(f"no such memory file: {rel}")
    all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, from_line)
    chunk = all_lines[start - 1:start - 1 + max(1, lines)]
    return {
        "file": rel,
        "from_line": start,
        "lines_returned": len(chunk),
        "total_lines": len(all_lines),
        "content": "\n".join(chunk),
    }


def save_fact(store: Path, text: str, topic: str = None) -> dict:
    init_store(store)
    text = " ".join(text.split())
    if not text:
        raise ValueError("nothing to save")
    bullet = f"- [{_today()}] {text}"
    if topic:
        rel = f"topics/{_slugify(topic)}.md"
        target = _safe_path(store, rel)
        if not target.exists():
            target.write_text(f"# {topic}\n\n", encoding="utf-8")
        with target.open("a", encoding="utf-8") as fh:
            fh.write(bullet + "\n")
        return {"saved_to": rel, "entry": bullet}
    target = store / "MEMORY.md"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(bullet + "\n")
    return {"saved_to": "MEMORY.md", "entry": bullet}


def log_entry(store: Path, text: str) -> dict:
    init_store(store)
    text = " ".join(text.split())
    if not text:
        raise ValueError("nothing to log")
    rel = f"logs/{_today()}.md"
    target = _safe_path(store, rel)
    entry = f"- {_now_time()} — {text}"
    if not target.exists():
        target.write_text(f"# {_today()}\n\n", encoding="utf-8")
    with target.open("a", encoding="utf-8") as fh:
        fh.write(entry + "\n")
    return {"logged_to": rel, "entry": entry}


def status(store: Path) -> dict:
    files = []
    total_lines = 0
    for path in _iter_md_files(store):
        try:
            n = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            n = 0
        total_lines += n
        files.append({"file": str(path.relative_to(store)), "lines": n})
    return {
        "store": str(store),
        "exists": store.exists(),
        "files": files,
        "file_count": len(files),
        "total_lines": total_lines,
        "version": VERSION,
    }


# ----------------------------------------------------------------- MCP ----

TOOLS = [
    {
        "name": "memory_search",
        "description": "Search the user's persistent memory (markdown files) "
                       "for facts relevant to a query. Returns ranked lines "
                       "with file and line citations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_get",
        "description": "Read a memory file (or a window of it) from the store.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "from_line": {"type": "integer", "default": 1},
                "lines": {"type": "integer", "default": 200},
            },
            "required": ["path"],
        },
    },
    {
        "name": "memory_save",
        "description": "Save a durable fact to persistent memory. Goes to "
                       "MEMORY.md, or to topics/<topic>.md when a topic is given.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "topic": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "memory_log",
        "description": "Append a timestamped entry to today's daily log.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "memory_status",
        "description": "Report the memory store location, files, and size.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def call_tool(store: Path, name: str, args: dict):
    if name == "memory_search":
        return search(store, args.get("query", ""), int(args.get("limit", 8)))
    if name == "memory_get":
        return get_file(store, args.get("path", ""),
                        int(args.get("from_line", 1)), int(args.get("lines", 200)))
    if name == "memory_save":
        return save_fact(store, args.get("text", ""), args.get("topic"))
    if name == "memory_log":
        return log_entry(store, args.get("text", ""))
    if name == "memory_status":
        return status(store)
    raise ValueError(f"unknown tool: {name}")


def _rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def handle_message(store: Path, msg: dict):
    """Return a response dict, or None for notifications."""
    method = msg.get("method", "")
    req_id = msg.get("id")
    if method == "initialize":
        return _rpc_result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "agent-memory", "version": VERSION},
        })
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return _rpc_result(req_id, {})
    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            out = call_tool(store, params.get("name", ""), params.get("arguments") or {})
            text = out if isinstance(out, str) else json.dumps(out, indent=2)
            return _rpc_result(req_id, {"content": [{"type": "text", "text": text}]})
        except Exception as exc:  # tool errors are reported, not fatal
            return _rpc_result(req_id, {
                "content": [{"type": "text", "text": f"error: {exc}"}],
                "isError": True,
            })
    if req_id is not None:
        return _rpc_error(req_id, -32601, f"method not found: {method}")
    return None


def serve(store: Path):
    init_store(store)
    print(f"agent-memory {VERSION} serving store {store}", file=sys.stderr)
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            print(f"agent-memory: skipped non-JSON line", file=sys.stderr)
            continue
        resp = handle_message(store, msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


# ----------------------------------------------------------------- CLI ----

def main(argv=None):
    parser = argparse.ArgumentParser(prog="agent-memory",
                                     description="Portable persistent memory for AI agents")
    parser.add_argument("--store", default=None,
                        help="memory store directory (default: $AGENT_MEMORY_DIR or ~/.agent-memory)")
    parser.add_argument("--version", action="version", version=f"agent-memory {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the memory store")
    p = sub.add_parser("search", help="search memory")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=8)
    p = sub.add_parser("get", help="read a memory file")
    p.add_argument("path")
    p.add_argument("--from", dest="from_line", type=int, default=1)
    p.add_argument("--lines", type=int, default=200)
    p = sub.add_parser("save", help="save a durable fact")
    p.add_argument("text")
    p.add_argument("--topic", default=None)
    p = sub.add_parser("log", help="append to today's daily log")
    p.add_argument("text")
    sub.add_parser("status", help="store status")
    sub.add_parser("serve", help="run the MCP stdio server")

    args = parser.parse_args(argv)
    store = resolve_store(args.store)

    try:
        if args.cmd == "init":
            out = init_store(store)
        elif args.cmd == "search":
            out = search(store, args.query, args.limit)
        elif args.cmd == "get":
            out = get_file(store, args.path, args.from_line, args.lines)
        elif args.cmd == "save":
            out = save_fact(store, args.text, args.topic)
        elif args.cmd == "log":
            out = log_entry(store, args.text)
        elif args.cmd == "status":
            out = status(store)
        elif args.cmd == "serve":
            serve(store)
            return 0
        else:
            parser.error(f"unknown command {args.cmd}")
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(out, indent=2) if not isinstance(out, str) else out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
