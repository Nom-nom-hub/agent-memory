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
            self.assertEqual(len(names), 10)
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


class FieldReport031Tests(unittest.TestCase):
    """v0.3.1 regressions — the three bugs from the 0.3.0 field check."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "s"
        am.init_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_brief_matches_inflected_word_forms(self):
        # Field bug 1: context said 'deploying', the lesson said 'deploy',
        # exact-word matching dropped the warning entirely.
        am.learn_lesson(self.store, situation="deploy the release",
                        rule="verify the live site after")
        out = am.brief(self.store, context="deploying the release to production")
        self.assertGreaterEqual(out["warnings"], 1)
        self.assertIn("verify the live site after", out["brief"])
        self.assertFalse(out["warnings_fallback"])

    def test_brief_warnings_never_drop_to_zero(self):
        am.learn_lesson(self.store, situation="sending invoices",
                        rule="review drafts before sending")
        out = am.brief(self.store, context="completely unrelated zebras")
        self.assertEqual(out["warnings"], 1)
        self.assertTrue(out["warnings_fallback"])
        self.assertIn("most recent lessons", out["brief"])

    def test_search_ignores_template_prose_in_root_files(self):
        # Field bug 2: 'outrank' and 'durable' appear only in the shipped
        # template prose of LESSONS.md / MEMORY.md — they are not memories.
        self.assertEqual(am.search(self.store, "outrank"), [])
        self.assertEqual(am.search(self.store, "durable"), [])
        am.save_fact(self.store, "durable goods ship on Fridays")
        hits = am.search(self.store, "durable")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "fact")

    def test_template_prose_cannot_take_the_lesson_boost(self):
        am.save_fact(self.store, "facts and search ranking matter here")
        hits = am.search(self.store, "facts search ranking")
        self.assertTrue(all(h["file"] != "LESSONS.md" for h in hits))

    def test_topic_prose_remains_searchable(self):
        topic = self.store / "topics" / "notes.md"
        topic.write_text("# Notes\n\nA zephyr protocol paragraph.\n",
                         encoding="utf-8")
        hits = am.search(self.store, "zephyr")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "topic")

    def test_intention_matches_trigger_not_action(self):
        # Field bug 3: 'smoke suite' (words from the ACTION half) fired
        # an intention whose trigger was deploying.
        am.add_intention(self.store, "deploying to production",
                         "run the smoke test suite")
        out = am.brief(self.store, context="run the smoke suite now")
        self.assertEqual(out["intentions_triggered"], 0)
        out2 = am.brief(self.store, context="deploying to production tonight")
        self.assertEqual(out2["intentions_triggered"], 1)


class FieldReport032Tests(unittest.TestCase):
    """v0.3.2: stemmer -ss pairs + the two re-checked cosmetic findings."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "s"
        am.init_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stemmer_ss_pairs_match(self):
        for singular, plural in (("address", "addresses"),
                                 ("boss", "bosses"),
                                 ("class", "classes")):
            self.assertEqual(am._stem(singular), am._stem(plural),
                             f"{singular}/{plural}")
        # Previously-working pairs are unaffected.
        self.assertEqual(am._stem("deploys"), am._stem("deploy"))
        self.assertEqual(am._stem("tests"), am._stem("test"))
        self.assertEqual(am._stem("deploying"), am._stem("deploy"))

    def test_brief_matches_address_lesson(self):
        am.learn_lesson(self.store, situation="the office address changed",
                        rule="confirm the address before mailing")
        out = am.brief(self.store, context="updating the addresses file")
        self.assertGreaterEqual(out["warnings"], 1)
        self.assertFalse(out["warnings_fallback"])

    def _serve(self, payload: bytes):
        return subprocess.run(
            [sys.executable, str(ROOT / "agent_memory.py"),
             "--store", str(self.store), "serve"],
            input=payload, capture_output=True, timeout=30)

    def test_nan_and_infinity_ids_are_not_echoed(self):
        payload = (b'{"jsonrpc":"2.0","id":NaN,"method":"ping"}\n'
                   b'{"jsonrpc":"2.0","id":Infinity,"method":"ping"}\n'
                   b'{"jsonrpc":"2.0","id":9,"method":"ping"}\n')
        proc = self._serve(payload)
        self.assertEqual(proc.returncode, 0)
        text = proc.stdout.decode()
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)
        self.assertIn('"id": 9', text)  # the valid request still answered

    def test_empty_batch_gets_single_error_response(self):
        payload = b'[]\n{"jsonrpc":"2.0","id":9,"method":"ping"}\n'
        proc = self._serve(payload)
        self.assertEqual(proc.returncode, 0)
        lines = [json.loads(l) for l in proc.stdout.decode().splitlines()
                 if l.strip()]
        errors = [o for o in lines if isinstance(o, dict) and "error" in o]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error"]["code"], -32600)
        self.assertIn(9, [o.get("id") for o in lines])


class SurrogateStrayFileTests(unittest.TestCase):
    """v0.3.3: the stray 0-byte file, finally reproduced — a topic with a
    lone surrogate made write_text create topics/t-t.md and THEN fail
    encoding the heading, leaving a 0-byte file that status listed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "s"
        am.init_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _zero_byte_files(self):
        return [p for p in self.store.rglob("*.md") if p.stat().st_size == 0]

    def test_surrogate_topic_fails_cleanly_no_stray_file(self):
        with self.assertRaises(ValueError):
            am.save_fact(self.store, "text", "t\ud800t")
        self.assertFalse((self.store / "topics" / "t-t.md").exists())
        self.assertEqual(self._zero_byte_files(), [])
        files = [f["file"] for f in am.status(self.store)["files"]]
        self.assertNotIn("topics/t-t.md", files)

    def test_surrogate_text_rejected_without_side_effects(self):
        before = len(am._bullets(self.store, "MEMORY.md"))
        with self.assertRaises(ValueError):
            am.save_fact(self.store, "bad \ud800 text")
        self.assertEqual(len(am._bullets(self.store, "MEMORY.md")), before)
        with self.assertRaises(ValueError):
            am.log_entry(self.store, "bad \ud800 log")
        with self.assertRaises(ValueError):
            am.learn_lesson(self.store, situation="s \ud800", rule="r")
        with self.assertRaises(ValueError):
            am.add_intention(self.store, "t \ud800", "act")
        self.assertEqual(am._bullets(self.store, "LESSONS.md"), [])
        self.assertEqual(am._bullets(self.store, "INTENTIONS.md"), [])
        self.assertEqual(self._zero_byte_files(), [])

    def test_preexisting_topic_file_survives_a_rejected_save(self):
        am.save_fact(self.store, "original fact", topic="keepme")
        target = self.store / "topics" / "keepme.md"
        before = target.read_text(encoding="utf-8")
        # A rejected save aimed at a different (surrogate) topic must not
        # touch the existing file — and neither must one aimed at it with
        # bad text.
        with self.assertRaises(ValueError):
            am.save_fact(self.store, "bad \ud800", topic="keepme")
        self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_legit_unicode_still_saves_everywhere(self):
        out = am.save_fact(self.store, "le café ☕ est prêt", topic="日本語トピック")
        self.assertTrue((self.store / out["saved_to"]).is_file())
        am.learn_lesson(self.store, situation="café fermé", rule="vérifier avant")
        hits = am.search(self.store, "café")
        self.assertTrue(hits)


class CjkSearchTests(unittest.TestCase):
    """v0.3.4: the completion-check limitation — CJK memories were
    stored and readable but unsearchable, because the tokenizer only
    knew [a-z0-9'] and a CJK-only query produced zero tokens."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "s"
        am.init_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cjk_fact_is_searchable(self):
        am.save_fact(self.store, "東京は日本の首都です")
        self.assertTrue(am.search(self.store, "東京"))
        self.assertTrue(am.search(self.store, "首都"))
        self.assertTrue(am.search(self.store, "日本"))

    def test_cjk_query_with_no_match_returns_empty(self):
        am.save_fact(self.store, "東京は日本の首都です")
        self.assertEqual(am.search(self.store, "大阪"), [])

    def test_mixed_script_query(self):
        am.save_fact(self.store, "the meeting in 東京 starts at noon")
        hits = am.search(self.store, "meeting 東京")
        self.assertTrue(hits)
        self.assertIn("東京", hits[0]["text"])

    def test_cjk_lesson_surfaces_in_brief(self):
        am.learn_lesson(self.store, situation="東京の会議の前に",
                        rule="資料を先に送る")
        out = am.brief(self.store, context="東京の会議")
        self.assertGreaterEqual(out["warnings"], 1)
        self.assertFalse(out["warnings_fallback"])

    def test_tokenizer_units(self):
        toks = am._tokens_of("hello 東京 world")
        self.assertIn("hello", toks)
        self.assertIn("world", toks)
        self.assertIn("東京", toks)      # bigram
        self.assertIn("東", toks)        # unigram
        self.assertEqual(am._tokens_of("café"), ["cafe"])  # accent-folded


class UnicodeSearchTests(unittest.TestCase):
    """v0.3.5: consequences, not token pins. The 0.3.4 suite pinned
    _tokens_of('café') == ['caf'] and stayed green while the shipped
    claim about accent behavior ran exactly backwards (an unaccented
    query MISSED accented text) and whole scripts returned 0 hits."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "s"
        am.init_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unaccented_query_matches_accented_text_and_vice_versa(self):
        am.save_fact(self.store, "le café est prêt le matin")
        self.assertTrue(am.search(self.store, "cafe"))
        self.assertTrue(am.search(self.store, "café"))
        self.assertTrue(am.search(self.store, "CAFÉ"))

    def test_cyrillic_greek_hebrew_arabic_searchable(self):
        am.save_fact(self.store, "привет из москвы")
        am.save_fact(self.store, "καλημέρα κόσμε")
        am.save_fact(self.store, "שלום עולם")
        am.save_fact(self.store, "مرحبا بالعالم")
        self.assertTrue(am.search(self.store, "привет"))
        self.assertTrue(am.search(self.store, "καλημέρα"))
        self.assertTrue(am.search(self.store, "שלום"))
        self.assertTrue(am.search(self.store, "مرحبا"))

    def test_hangul_survives_the_fold(self):
        # Bare NFKD decomposes Hangul into Jamo; without the NFC
        # recompose, Korean goes unsearchable again — silently.
        am.save_fact(self.store, "한국어는 아름다운 언어입니다")
        self.assertTrue(am.search(self.store, "한국"))
        self.assertTrue(am.search(self.store, "한국어"))
        self.assertIn("한국", am._tokens_of("한국어"))

    def test_kana_and_han_still_work_after_fold(self):
        am.save_fact(self.store, "東京は日本の首都です")
        self.assertTrue(am.search(self.store, "首都"))
        am.save_fact(self.store, "ひらがなのテキスト")
        self.assertTrue(am.search(self.store, "ひらがな"))


class IndicAndUnsegmentedScriptTests(unittest.TestCase):
    """v0.3.6: the Mc gap — the third appearance of the same silent
    shape (CJK in 0.3.4, accents in 0.3.5). Indic vowel signs are
    category Mc: not word characters, so काम split into 1-char
    fragments the filter dropped, and search returned [] with no error.
    Thai/Lao/Burmese/Tibetan additionally need bigram indexing because
    they are written without word boundaries."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "s"
        am.init_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mc_vowel_signs_fold_to_consonant_skeleton(self):
        self.assertEqual(am._tokens_of("काम"), ["कम"])
        kept = [t for t in am._tokens_of("काम") if am._keep_token(t)]
        self.assertEqual(kept, ["कम"])

    def test_hindi_and_bengali_searchable(self):
        am.save_fact(self.store, "मेरा काम चल रहा है")
        self.assertTrue(am.search(self.store, "काम"))
        am.save_fact(self.store, "আমি ঢাকা যাই")
        self.assertTrue(am.search(self.store, "ঢাকা"))

    def test_thai_word_inside_unspaced_text(self):
        am.save_fact(self.store, "กรุงเทพมหานครเป็นเมืองหลวง")
        self.assertTrue(am.search(self.store, "กรุงเทพ"))

    def test_lao_burmese_tibetan_searchable(self):
        am.save_fact(self.store, "ສະບາຍດີຕອນເຊົ້າ")
        self.assertTrue(am.search(self.store, "ສະບາຍ"))
        am.save_fact(self.store, "မြန်မာဘာသာစကား")
        self.assertTrue(am.search(self.store, "မြန်မာ"))
        am.save_fact(self.store, "བོད་སྐད་ཡིག")
        self.assertTrue(am.search(self.store, "བོད"))

    def test_single_nonlatin_letter_query_never_silently_empty(self):
        am.save_fact(self.store, "क अक्षर से शुरू")
        self.assertTrue(am.search(self.store, "क"))


class ServerKillerRegressionTests(unittest.TestCase):
    """v0.2.2 regressions: the two remaining ways to kill the server."""

    def _run_server(self, payload: bytes, store: Path):
        return subprocess.run(
            [sys.executable, str(ROOT / "agent_memory.py"),
             "--store", str(store), "serve"],
            input=payload, capture_output=True, timeout=30)

    def _reply_ids(self, proc):
        ids = set()
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            for item in (obj if isinstance(obj, list) else [obj]):
                if isinstance(item, dict) and "id" in item:
                    ids.add(item["id"])
        return ids

    def test_deeply_nested_json_does_not_kill_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            # ~6 KB of nested objects (the reported size) and a much
            # deeper array nest for good measure.
            deep_obj = '{"x":' * 1000 + "1" + "}" * 1000
            deep_arr = "[" * 5000 + "]" * 5000
            lines = [
                '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
                deep_obj, deep_arr,
                '{"jsonrpc":"2.0","id":3,"method":"ping"}',
            ]
            proc = self._run_server(("\n".join(lines) + "\n").encode(),
                                    Path(tmp) / "s")
            self.assertEqual(proc.returncode, 0,
                             proc.stderr.decode(errors="replace"))
            ids = self._reply_ids(proc)
            self.assertIn(1, ids)
            self.assertIn(3, ids)  # ping after the nesting bombs answered

    def test_depth_guard_ignores_brackets_in_strings(self):
        self.assertEqual(am._max_json_depth('{"a": "[[[[{{{{"}'), 1)
        self.assertEqual(am._max_json_depth('{"a": {"b": [1, {"c": 2}]}}'), 4)
        self.assertGreater(am._max_json_depth("[" * 150 + "]" * 150), 100)

    def test_moderately_nested_legit_message_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = {"level": None}
            cur = nested
            for _ in range(40):
                cur["level"] = {"level": None}
                cur = cur["level"]
            msg = {"jsonrpc": "2.0", "id": 7, "method": "initialize",
                   "params": {"deep": nested}}
            proc = self._run_server((json.dumps(msg) + "\n").encode(),
                                    Path(tmp) / "s")
            self.assertEqual(proc.returncode, 0)
            self.assertIn(7, self._reply_ids(proc))

    def test_invalid_utf8_byte_does_not_kill_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "s"
            save = json.dumps({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "memory_save",
                           "arguments": {"text": "bad byte: X end"}},
            }).encode().replace(b"X", b"\xff")
            payload = (
                b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
                + b"\xff\xfe\x81 pure junk\n"
                + save + b"\n"
                + b'{"jsonrpc":"2.0","id":3,"method":"ping"}\n'
            )
            proc = self._run_server(payload, store)
            self.assertEqual(proc.returncode, 0,
                             proc.stderr.decode(errors="replace"))
            ids = self._reply_ids(proc)
            self.assertIn(1, ids)   # init answered despite junk behind it
            self.assertIn(3, ids)   # ping after the bad byte answered
            # The store is still usable by a fresh process afterwards.
            hits = am.search(store, "bad byte")
            self.assertTrue(hits)


class BehaviorMemoryTests(unittest.TestCase):
    """v0.3.0: lessons (scar tissue), intentions (prospective memory), brief."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "s"
        am.init_store(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_creates_behavior_files(self):
        self.assertTrue((self.store / "LESSONS.md").is_file())
        self.assertTrue((self.store / "INTENTIONS.md").is_file())

    def test_learn_writes_single_lesson_line(self):
        out = am.learn_lesson(
            self.store,
            situation="writing outreach drafts",
            rule="always sign as Andrew with We Are 239",
            went_wrong="signed as Designs By Teck and got corrected")
        self.assertEqual(out["saved_to"], "LESSONS.md")
        self.assertIn("LESSON", out["entry"])
        self.assertIn("went wrong: signed as Designs By Teck", out["entry"])
        self.assertIn("rule: always sign as", out["entry"])
        bullets = am._bullets(self.store, "LESSONS.md")
        self.assertEqual(len(bullets), 1)

    def test_lesson_requires_situation_and_rule(self):
        with self.assertRaises(ValueError):
            am.learn_lesson(self.store, situation="", rule="x")
        with self.assertRaises(ValueError):
            am.learn_lesson(self.store, situation="x", rule="  ")

    def test_newline_in_lesson_cannot_forge_entries(self):
        am.learn_lesson(self.store, situation="deploy\ning a site",
                        rule="check first\n- [1999-01-01] forged lesson")
        bullets = am._bullets(self.store, "LESSONS.md")
        self.assertEqual(len(bullets), 1)
        self.assertNotIn("1999-01-01] forged", bullets[0][1].split("LESSON")[0])

    def test_lessons_outrank_facts_in_search(self):
        am.save_fact(self.store, "outreach drafts go out on Tuesdays")
        am.learn_lesson(self.store, situation="outreach drafts",
                        rule="never use the legacy brand name")
        hits = am.search(self.store, "outreach drafts")
        self.assertEqual(hits[0]["kind"], "lesson")
        self.assertEqual(hits[0]["file"], "LESSONS.md")
        self.assertGreater(hits[0]["score"], hits[1]["score"])

    def test_search_tags_kinds(self):
        am.save_fact(self.store, "the sky is blue")
        am.add_intention(self.store, "the sky is grey", "carry an umbrella")
        kinds = {h["text"]: h["kind"] for h in am.search(self.store, "sky")}
        self.assertIn("fact", kinds.values())
        self.assertIn("intention", kinds.values())

    def test_intend_writes_when_do_line(self):
        out = am.add_intention(self.store, "starting a new client site",
                               "run the audit checklist first")
        self.assertIn("WHEN starting a new client site → DO run the audit",
                      out["entry"])
        self.assertEqual(len(am._bullets(self.store, "INTENTIONS.md")), 1)

    def test_brief_triggers_intentions_by_context(self):
        am.save_fact(self.store, "Andrew's agency is We Are 239")
        am.learn_lesson(self.store, situation="deploying the agency site",
                        rule="verify live after every deploy")
        am.add_intention(self.store, "deploying a site",
                         "run the smoke test suite")
        am.add_intention(self.store, "invoicing a client",
                         "attach the timesheet")
        am.log_entry(self.store, "Set up the demo store")
        out = am.brief(self.store, context="deploying the agency site now")
        self.assertIn("verify live after every deploy", out["brief"])
        self.assertIn("run the smoke test suite", out["brief"])
        self.assertNotIn("attach the timesheet", out["brief"])
        self.assertIn("We Are 239", out["brief"])
        self.assertEqual(out["intentions_triggered"], 1)
        self.assertEqual(out["warnings"], 1)

    def test_brief_without_context_shows_recent_lessons_and_all_intentions(self):
        am.learn_lesson(self.store, situation="a", rule="rule one")
        am.add_intention(self.store, "trigger x", "action y")
        out = am.brief(self.store)
        self.assertIn("rule one", out["brief"])
        self.assertIn("action y", out["brief"])
        self.assertEqual(out["lessons_total"], 1)
        self.assertEqual(out["intentions_total"], 1)

    def test_brief_empty_store_does_not_crash(self):
        out = am.brief(self.store, context="anything")
        self.assertIn("(none yet)", out["brief"])

    def test_forget_can_remove_a_lesson(self):
        am.learn_lesson(self.store, situation="email sends",
                        rule="always check the Sent folder")
        out = am.forget(self.store, "check the Sent folder")
        self.assertEqual(out["removed_count"], 1)
        self.assertEqual(am._bullets(self.store, "LESSONS.md"), [])

    def test_status_counts_behavior_memory(self):
        am.learn_lesson(self.store, situation="a", rule="b")
        am.add_intention(self.store, "t", "act")
        st = am.status(self.store)
        self.assertEqual(st["lessons"], 1)
        self.assertEqual(st["intentions"], 1)

    def test_behavior_tools_over_mcp(self):
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "memory_learn", "arguments": {
                    "situation": "sending invoices",
                    "went_wrong": "sent a draft by mistake",
                    "rule": "drafts are reviewed before sending"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "memory_intend", "arguments": {
                    "trigger": "sending an invoice",
                    "action": "double-check the total"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "memory_brief", "arguments": {
                    "context": "sending an invoice to a client"}}},
        ]
        payload = ("\n".join(json.dumps(m) for m in lines) + "\n").encode()
        proc = subprocess.run(
            [sys.executable, str(ROOT / "agent_memory.py"),
             "--store", str(self.store), "serve"],
            input=payload, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode(errors="replace"))
        replies = {json.loads(l)["id"]: json.loads(l)
                   for l in proc.stdout.decode().splitlines() if l.strip()}
        brief_text = replies[4]["result"]["content"][0]["text"]
        self.assertIn("drafts are reviewed before sending", brief_text)
        self.assertIn("double-check the total", brief_text)
        tools = am.TOOLS
        self.assertEqual(len(tools), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
