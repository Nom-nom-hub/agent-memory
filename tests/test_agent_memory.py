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


if __name__ == "__main__":
    unittest.main(verbosity=2)
