#!/usr/bin/env python3
"""Agent Memory — portable, local-first persistent memory for AI agents.

Memory is plain markdown files in a folder the user owns. This single file
(standard library only) serves that store two ways:

  * as an MCP server over stdio (tools: memory_search, memory_get,
    memory_save, memory_log, memory_forget, memory_recent, memory_status), and
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
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

VERSION = "0.2.2"

# Legitimate MCP messages nest maybe a dozen levels. Anything past this
# is hostile or broken, and deep nesting is exactly what makes the JSON
# parser recurse toward the C stack limit (platform-dependent).
MAX_JSON_DEPTH = 100
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


def _within_store(store: Path, target: Path) -> bool:
    resolved_store = store.resolve()
    resolved = target.resolve()
    return resolved == resolved_store or resolved_store in resolved.parents


def _safe_path(store: Path, rel: str) -> Path:
    """Resolve rel inside the store. Refuse anything that escapes it —
    including paths that escape through a symlink or junction."""
    rel = str(rel).replace("\\", "/")
    target = (store / rel).resolve()
    if not _within_store(store, target):
        raise ValueError(f"path escapes the memory store: {rel!r}")
    return target


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-")
    if not slug:
        # Topics with no ASCII slug (e.g. Japanese) get a stable hash name
        # instead of all collapsing into one shared "notes" file.
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        slug = f"topic-{digest}"
    return slug


def _iter_md_files(store: Path):
    """Yield markdown files that genuinely live inside the store.

    rglob follows symlinks/junctions, so every candidate is re-validated:
    a link pointing outside the store must not make outside files
    searchable, readable, or — via forget — writable.
    """
    if not store.exists():
        return
    for path in sorted(store.rglob("*.md")):
        if path.is_file() and _within_store(store, path):
            yield path


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _now_time() -> str:
    return datetime.now().astimezone().strftime("%H:%M")


# ------------------------------------------------------------ operations ----

def search(store: Path, query: str, limit: int = 8) -> list:
    limit = _as_int(limit, 8, 1, 50)
    all_tokens = [t for t in re.findall(r"[a-z0-9']+", str(query).lower()) if len(t) >= 2]
    tokens = [t for t in all_tokens if t not in STOPWORDS] or all_tokens
    if not tokens:
        return []
    phrase = str(query).strip().lower()
    results = []
    for path in _iter_md_files(store):
        rel = path.relative_to(store).as_posix()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, start=1):
            low = line.lower()
            words = re.findall(r"[a-z0-9']+", low)
            hits = sum(words.count(t) for t in tokens)
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
        "file": target.relative_to(store.resolve()).as_posix()
        if _within_store(store, target) else str(rel).replace("\\", "/"),
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
        # The heading is written raw into the file, so it gets the same
        # single-line normalization as the text — otherwise a newline in
        # the topic could inject fabricated, dated "facts" as file lines.
        heading = " ".join(str(topic).split()) or "Notes"
        rel = f"topics/{_slugify(heading)}.md"
        target = _safe_path(store, rel)
        if not target.exists():
            target.write_text(f"# {heading}\n\n", encoding="utf-8")
        with target.open("a", encoding="utf-8") as fh:
            fh.write(bullet + "\n")
        return {"saved_to": rel, "entry": bullet}
    target = _safe_path(store, "MEMORY.md")
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


def forget(store: Path, text: str, only_file: str = None) -> dict:
    """Remove memory lines containing `text` (case-insensitive).

    Headings are never removed. Returns exactly what was removed, with
    citations, so a human can audit the correction.
    """
    needle = " ".join(text.split()).lower()
    if not needle:
        raise ValueError("nothing to forget")
    removed = []
    paths = [_safe_path(store, only_file)] if only_file else list(_iter_md_files(store))
    for path in paths:
        if not path.is_file():
            continue
        try:
            rel = path.resolve().relative_to(store.resolve()).as_posix()
        except ValueError:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        kept = []
        for i, line in enumerate(lines, start=1):
            if needle in line.lower() and not line.lstrip().startswith("#"):
                removed.append({"file": rel, "line": i, "text": line.strip()[:240]})
            else:
                kept.append(line)
        if len(kept) != len(lines):
            path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return {"forgot": needle, "removed_count": len(removed), "removed": removed}


_DATE_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def recent(store: Path, limit: int = 10) -> list:
    """Most recent memory entries: newest daily-log bullets first.

    Only date-named log files (YYYY-MM-DD.md) count — any other file a
    user drops into logs/ is not a daily log and must not pose as one.
    """
    limit = _as_int(limit, 10, 1, 100)
    out = []
    logs_dir = store / "logs"
    if logs_dir.is_dir():
        dated = [p for p in logs_dir.glob("*.md")
                 if _DATE_FILE.match(p.name) and _within_store(store, p)]
        for path in sorted(dated, reverse=True):
            rel = path.relative_to(store).as_posix()
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for i in range(len(lines), 0, -1):
                line = lines[i - 1].strip()
                if line.startswith("- "):
                    out.append({"file": rel, "line": i, "text": line[:240]})
                    if len(out) >= limit:
                        return out
    return out


def status(store: Path) -> dict:
    if store.exists() and not store.is_dir():
        raise NotADirectoryError(f"store path is a file, not a directory: {store}")
    files = []
    total_lines = 0
    for path in _iter_md_files(store):
        try:
            n = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            n = 0
        total_lines += n
        files.append({"file": path.relative_to(store).as_posix(), "lines": n})
    return {
        "store": str(store),
        "exists": store.exists(),
        "files": files,
        "file_count": len(files),
        "total_lines": total_lines,
        "version": VERSION,
    }


def _as_int(value, default: int, lo: int, hi: int) -> int:
    """Tolerant int coercion for tool arguments: bad values fall back to
    the default instead of leaking a ValueError message, and the result
    is always clamped into [lo, hi]."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _as_text(value, field: str) -> str:
    if value is None:
        raise ValueError(f"{field} is required")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


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
        "name": "memory_forget",
        "description": "Remove memory lines containing the given text "
                       "(case-insensitive), across the store or in one file. "
                       "Use to correct or delete a wrong/outdated memory. "
                       "Returns exactly what was removed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "file": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "memory_recent",
        "description": "Return the most recent daily-log entries, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        },
    },
    {
        "name": "memory_status",
        "description": "Report the memory store location, files, and size.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def call_tool(store: Path, name: str, args: dict):
    if not isinstance(args, dict):
        raise ValueError("tool arguments must be an object")
    if name == "memory_search":
        return search(store, _as_text(args.get("query"), "query"),
                      _as_int(args.get("limit", 8), 8, 1, 50))
    if name == "memory_get":
        return get_file(store, _as_text(args.get("path"), "path"),
                        _as_int(args.get("from_line", 1), 1, 1, 1_000_000),
                        _as_int(args.get("lines", 200), 200, 1, 1000))
    if name == "memory_save":
        topic = args.get("topic")
        if topic is not None and not isinstance(topic, str):
            raise ValueError("topic must be a string")
        return save_fact(store, _as_text(args.get("text"), "text"), topic)
    if name == "memory_log":
        return log_entry(store, _as_text(args.get("text"), "text"))
    if name == "memory_forget":
        only = args.get("file")
        if only is not None and not isinstance(only, str):
            raise ValueError("file must be a string")
        return forget(store, _as_text(args.get("text"), "text"), only)
    if name == "memory_recent":
        return recent(store, _as_int(args.get("limit", 10), 10, 1, 100))
    if name == "memory_status":
        return status(store)
    raise ValueError(f"unknown tool: {name}")


def _rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def handle_message(store: Path, msg):
    """Return a response dict, or None for notifications.

    Robust by design: a malformed or unexpected message must never be
    able to kill the server loop. Non-object messages, non-string
    methods, and notification-form requests (no id) never produce a
    response — and notification-form tool calls are not executed.
    """
    if not isinstance(msg, dict):
        return None
    method = msg.get("method")
    if not isinstance(method, str):
        req_id = msg.get("id")
        if req_id is not None:
            return _rpc_error(req_id, -32600, "invalid request: method must be a string")
        return None
    req_id = msg.get("id")
    if req_id is None:
        # Notification form: JSON-RPC forbids replying, and a request
        # shaped like a notification must not mutate the store.
        return None
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
        if not isinstance(params, dict):
            params = {}
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


def _force_utf8_stdio():
    """The MCP transport is UTF-8 — always. Without this, Windows decodes
    stdin with the locale codepage (e.g. cp1252) and non-ASCII memory text
    is silently double-encoded on its way into the store. errors="replace"
    matters just as much: one invalid byte must degrade to U+FFFD in that
    one message, never raise out of the read loop and kill the server."""
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _iter_input_lines():
    """Yield input lines as text, decoding bytes ourselves.

    Reading the binary buffer and decoding per line with errors="replace"
    means an invalid UTF-8 byte can never raise during iteration — the
    failure mode that replaced the cp1252 bug in v0.2.1 (a strict UTF-8
    text wrapper reads ahead in chunks, so one bad byte killed even the
    well-formed messages buffered behind it).
    """
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        for raw_bytes in buffer:
            yield raw_bytes.decode("utf-8", errors="replace")
    else:
        _force_utf8_stdio()
        yield from sys.stdin


def _max_json_depth(raw: str) -> int:
    """Bracket depth of a JSON text, ignoring brackets inside strings."""
    depth = max_depth = 0
    in_str = escaped = False
    for ch in raw:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif ch in "]}":
            depth -= 1
    return max_depth


def serve(store: Path):
    _force_utf8_stdio()
    init_store(store)
    print(f"agent-memory {VERSION} serving store {store}", file=sys.stderr)
    for raw in _iter_input_lines():
        raw = raw.strip().lstrip("﻿").strip()  # tolerate a stray BOM
        if not raw:
            continue
        if _max_json_depth(raw) > MAX_JSON_DEPTH:
            print("agent-memory: skipped absurdly nested JSON message",
                  file=sys.stderr)
            continue
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            print("agent-memory: skipped unparseable line", file=sys.stderr)
            continue
        try:
            if isinstance(msg, list):
                # Legal JSON-RPC batch: answer each request, skip notifications.
                resps = [r for r in (handle_message(store, m) for m in msg)
                         if r is not None]
                resp = resps if resps else None
            elif isinstance(msg, dict):
                resp = handle_message(store, msg)
            else:
                print("agent-memory: skipped non-object JSON message",
                      file=sys.stderr)
                continue
        except Exception as exc:  # one bad message must not kill the session
            req_id = msg.get("id") if isinstance(msg, dict) else None
            if req_id is None:
                print(f"agent-memory: dropped bad message: {exc}", file=sys.stderr)
                continue
            resp = _rpc_error(req_id, -32603, f"internal error: {exc}")
        if resp is not None:
            try:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, RecursionError, ValueError) as exc:
                print(f"agent-memory: could not send response: {exc}",
                      file=sys.stderr)
                if isinstance(exc, BrokenPipeError):
                    break


# ----------------------------------------------------------------- CLI ----

def main(argv=None):
    _force_utf8_stdio()
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
    p = sub.add_parser("forget", help="remove memory lines containing text")
    p.add_argument("text")
    p.add_argument("--file", default=None)
    p = sub.add_parser("recent", help="most recent daily-log entries")
    p.add_argument("--limit", type=int, default=10)
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
        elif args.cmd == "forget":
            out = forget(store, args.text, args.file)
        elif args.cmd == "recent":
            out = recent(store, args.limit)
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
    except OSError as exc:
        print(f"error: cannot use memory store at {store}: {exc}. "
              "Check that the path is a writable directory, or point "
              "--store / $AGENT_MEMORY_DIR somewhere else.", file=sys.stderr)
        return 1

    print(json.dumps(out, indent=2) if not isinstance(out, str) else out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
