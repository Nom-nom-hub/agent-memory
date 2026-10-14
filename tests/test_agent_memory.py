import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent_memory as am


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        am.init_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_creates_structure(self):
        self.assertTrue((self.store / "MEMORY.md").is_file())
        self.assertTrue((self.store / "logs").is_dir())
        self.assertTrue((self.store / "topics").is_dir())

    def test_save_and_search_roundtrip(self):
        am.save_fact(self.store, "The user's dog is named Biscuit")
        hits = am.search(self.store, "dog biscuit")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["file"], "MEMORY.md")
        self.assertIn("Biscuit", hits[0]["text"])

    def test_search_no_match(self):
        self.assertEqual(am.search(self.store, "zzzqqq nonexistent"), [])

    def test_topic_save(self):
        out = am.save_fact(self.store, "Prefers dark themes", topic="UI Preferences!")
        self.assertEqual(out["saved_to"], "topics/ui-preferences.md")
        hits = am.search(self.store, "dark themes")
        self.assertEqual(hits[0]["file"], "topics/ui-preferences.md")

    def test_daily_log(self):
        out = am.log_entry(self.store, "Shipped the v1 build")
        self.assertTrue(out["logged_to"].startswith("logs/"))
        self.assertTrue((self.store / out["logged_to"]).is_file())

    def test_get_file_window(self):
        am.save_fact(self.store, "line about apples")
        got = am.get_file(self.store, "MEMORY.md")
        self.assertIn("apples", got["content"])

    def test_path_traversal_blocked(self):
        with self.assertRaises(ValueError):
            am.get_file(self.store, "../../etc/passwd")
        with self.assertRaises(ValueError):
            am.get_file(self.store, "/etc/passwd")
        # Topic names are slugified, so a traversal attempt is neutralised
        # into a plain file inside topics/ — it can never escape the store.
        out = am.save_fact(self.store, "x", topic="../../evil")
        self.assertEqual(out["saved_to"], "topics/evil.md")
        self.assertTrue((self.store / "topics" / "evil.md").is_file())

    def test_forget_removes_only_matching_lines(self):
        am.save_fact(self.store, "The old office is in Tampa")
        am.save_fact(self.store, "The new office is in Cape Coral")
        out = am.forget(self.store, "old office is in Tampa")
        self.assertEqual(out["removed_count"], 1)
        self.assertEqual(am.search(self.store, "Tampa"), [])
        self.assertTrue(am.search(self.store, "Cape Coral"))

    def test_forget_keeps_headings(self):
        out = am.forget(self.store, "MEMORY")
        self.assertEqual(out["removed_count"], 0)

    def test_recent_returns_newest_log_entries(self):
        am.log_entry(self.store, "first thing")
        am.log_entry(self.store, "second thing")
        out = am.recent(self.store, limit=1)
        self.assertEqual(len(out), 1)
        self.assertIn("second thing", out[0]["text"])

    def test_status_counts(self):
        am.save_fact(self.store, "something countable")
        st = am.status(self.store)
        self.assertGreaterEqual(st["file_count"], 1)
        self.assertGreater(st["total_lines"], 0)


class McpTests(unittest.TestCase):
    def test_mcp_stdio_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = str(Path(tmp) / "store")
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "memory_save",
                            "arguments": {"text": "The launch code is ORBIT-7"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "memory_search",
                            "arguments": {"query": "launch code ORBIT"}}},
            ]
            proc = subprocess.run(
                [sys.executable, str(ROOT / "agent_memory.py"),
                 "--store", store, "serve"],
                input="\n".join(json.dumps(m) for m in msgs) + "\n",
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            replies = {}
            for line in proc.stdout.splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                if "id" in obj:
                    replies[obj["id"]] = obj
            self.assertIn("result", replies[1])
            names = [t["name"] for t in replies[2]["result"]["tools"]]
            self.assertEqual(len(names), 7)
            self.assertIn("memory_search", names)
            self.assertIn("memory_forget", names)
            self.assertIn("memory_recent", names)
            found = replies[4]["result"]["content"][0]["text"]
            self.assertIn("ORBIT-7", found)


class RegressionTests(unittest.TestCase):
    """Regressions for GitHub issues #1, #2, #3 (filed by a testing agent)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        am.init_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    # --- #2: the server loop survives anything -------------------------
    def test_handle_message_non_object(self):
        for bad in (None, 123, "hello", 4.5, True):
            self.assertIsNone(am.handle_message(self.store, bad))

    def test_handle_message_bad_method_type(self):
        out = am.handle_message(self.store, {"jsonrpc": "2.0", "id": 2, "method": None})
        self.assertIn("error", out)
        out = am.handle_message(self.store, {"jsonrpc": "2.0", "id": 2, "method": 123})
        self.assertIn("error", out)

    def test_notification_form_tool_call_does_not_mutate(self):
        before = am.status(self.store)["total_lines"]
        out = am.handle_message(self.store, {
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "memory_save", "arguments": {"text": "sneaky"}},
        })
        self.assertIsNone(out)
        self.assertEqual(am.status(self.store)["total_lines"], before)
        self.assertEqual(am.search(self.store, "sneaky"), [])

    def test_server_survives_garbage_and_batch_then_answers_ping(self):
        store = str(self.store)
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            "null", "123", '"hello"',
            [{"jsonrpc": "2.0", "id": 9, "method": "ping"}],
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        ]
        payload = "\n".join(
            x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "agent_memory.py"),
             "--store", store, "serve"],
            input=payload, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        replies = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
        flat = []
        for r in replies:
            flat.extend(r if isinstance(r, list) else [r])
        ids = {r.get("id") for r in flat}
        self.assertIn(9, ids)   # batch answered
        self.assertIn(3, ids)   # ping after the garbage answered

    # --- #1: UTF-8 on the wire stays UTF-8 in the store -----------------
    def test_mcp_utf8_roundtrip_bytes(self):
        store = Path(self.tmp.name) / "ustore"
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "memory_save",
                        "arguments": {"text": "café — naïve", "topic": "t"}}},
        ]
        payload = ("\n".join(json.dumps(m) for m in msgs) + "\n").encode("utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "agent_memory.py"),
             "--store", str(store), "serve"],
            input=payload, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        raw = (store / "topics" / "t.md").read_bytes()
        text = raw.decode("utf-8")
        self.assertIn("café — naïve", text)
        self.assertNotIn("Ã", text)  # double-encoded mojibake marker

    # --- #3.1: containment holds through links --------------------------
    def test_symlink_escape_not_searchable_not_forgettable(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        secret = outside / "secret.md"
        secret.write_text("# secret\n\n- confidential token ABC123\n", encoding="utf-8")
        link = self.store / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        self.assertEqual(am.search(self.store, "confidential"), [])
        out = am.forget(self.store, "confidential")
        self.assertEqual(out["removed_count"], 0)
        self.assertIn("ABC123", secret.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            am.get_file(self.store, "link/secret.md")

    # --- #3.2: topic cannot inject fake fact lines -----------------------
    def test_topic_newline_cannot_inject_fact(self):
        am.save_fact(self.store, "real fact",
                     topic="x\n- [2026-01-01] INJECTED FAKE FACT")
        files = list((self.store / "topics").glob("*.md"))
        self.assertEqual(len(files), 1)
        lines = files[0].read_text(encoding="utf-8").splitlines()
        fact_lines = [l for l in lines if l.startswith("- [")]
        self.assertEqual(len(fact_lines), 1)
        self.assertIn("real fact", fact_lines[0])
        self.assertTrue(lines[0].startswith("# x - [2026-01-01] INJECTED"))

    # --- #3.3: paths are POSIX across the API ----------------------------
    def test_get_returns_posix_path(self):
        am.save_fact(self.store, "posix check", topic="paths")
        got = am.get_file(self.store, "topics/paths.md")
        self.assertEqual(got["file"], "topics/paths.md")
        hits = am.search(self.store, "posix check")
        self.assertNotIn("\\", hits[0]["file"])

    # --- #3.4: smaller findings -------------------------------------------
    def test_non_latin_topic_gets_own_file(self):
        out = am.save_fact(self.store, "japanese topic fact", topic="日本語")
        self.assertNotEqual(out["saved_to"], "topics/notes.md")
        self.assertTrue((self.store / out["saved_to"]).is_file())

    def test_argument_coercion_is_tolerant(self):
        am.save_fact(self.store, "coercion target fact")
        out = am.call_tool(self.store, "memory_search",
                           {"query": "coercion", "limit": "abc"})
        self.assertTrue(out)
        out = am.call_tool(self.store, "memory_recent", {"limit": None})
        self.assertIsInstance(out, list)
        out = am.call_tool(self.store, "memory_search",
                           {"query": "coercion", "limit": -5})
        self.assertLessEqual(len(out), 50)

    def test_search_whole_word_and_stopword_phrase(self):
        am.save_fact(self.store, "the quick brown fox jumps")
        am.save_fact(self.store, "concatenate strings in code")
        hits = am.search(self.store, "cat")
        self.assertEqual(hits, [])
        hits = am.search(self.store, "the quick brown")
        self.assertTrue(hits)

    def test_recent_ignores_non_date_files_in_logs(self):
        am.log_entry(self.store, "real log entry")
        (self.store / "logs" / "notes.md").write_text(
            "# notes\n\n- fake recent entry\n", encoding="utf-8")
        out = am.recent(self.store)
        self.assertTrue(out)
        self.assertTrue(all("notes.md" not in e["file"] for e in out))

    def test_store_path_is_a_file_gives_clean_error(self):
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "agent_memory.py"),
             "--store", str(blocker), "status"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("cannot use memory store", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
