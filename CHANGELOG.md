# Changelog

## 0.3.4 — 2026-10-14

**CJK search.** The completion check's one remaining limitation,
pre-existing in every version: the search tokenizer only knew
`[a-z0-9']`, so a Japanese/Chinese/Korean query produced zero tokens
and returned `[]` — CJK memories were stored and readable via
`memory_get`/`memory_brief` but silently unsearchable.

- New shared tokenizer used by search and by brief context matching:
  Latin-script words stay whole; CJK runs (Han, Hiragana, Katakana,
  Hangul) index as character unigrams + bigrams — the standard approach
  for scripts without word boundaries, no segmenter required.
- Consequences: CJK facts, lessons, and intentions are now searchable
  and match brief contexts; mixed-script queries ("meeting 東京") work;
  adjacent-character matches naturally outscore scattered ones.
- Known remaining property, pinned by test rather than left implicit:
  accented Latin characters split tokens ("café" indexes as "caf") —
  unchanged from earlier versions.
- Test suite: 56 → 61.

## 0.3.3 — 2026-10-14

**The stray 0-byte file — reproduced and fixed.** The 0.3.2 entry marked
it not-reproduced; the field re-check found the exact trigger:
`save_fact(store, "text", "t\ud800t")` — a *topic* containing a lone
surrogate. The topic-heading `write_text` created `topics/t-t.md` first
and failed encoding second, leaving a 0-byte file that `memory_status`
then listed as a memory file. (The 0.3.2 probes had aimed at the text
and at filesystem paths, never at the heading write — repro matters.)

Fix, two layers:
- Every write operation (save, log, learn, intend) now validates that
  its text can be encoded as UTF-8 **before touching the filesystem**
  and rejects lone surrogates with a clean `ValueError` — over MCP the
  caller gets a readable tool error, not a raw `UnicodeEncodeError`.
- File creation for topic/log headings now encodes first and writes
  bytes, so a failure can never again leave a created-but-empty file.
- Nothing is ever deleted by the fix path: pre-existing topic files are
  untouched by rejected saves (regression-tested), and legitimate
  non-ASCII content (café, CJK topics, emoji) saves exactly as before.
- Test suite: 52 → 56, including the field repro verbatim.

## 0.3.2 — 2026-10-14

From the 0.3.1 confirmation session — the suggested stemmer fix,
applied, plus the two outstanding cosmetic findings re-checked at this
version (both reproduced, both fixed):

- **Stemmer `-ss` pairs.** `address/addresses`, `boss/bosses`, and
  `class/classes` did not match: the trailing-s rule stemmed "address"
  to "addres" while "addresses" stemmed to "address". Words ending in
  `-ss` now keep their final s. (The warnings fallback had been covering
  this gap; now the match itself works.)
- **NaN / Infinity response ids.** Python's `json` accepts these
  non-standard constants, so a request with `"id": NaN` got a response
  echoing `NaN` — invalid JSON that strict clients can't parse. Such
  lines are now rejected at parse time (`parse_constant`) and skipped
  like any other unparseable input.
- **Empty batch silence.** A batch of `[]` previously got no response
  at all; JSON-RPC 2.0 defines it as invalid, so it now gets a single
  `-32600` error response.
- Also probed, **not reproduced** (at the time): a stray 0-byte file
  from a failed save (empty-text topic save, topic-path-is-a-directory,
  and log-path-is-a-directory scenarios all fail cleanly with no stray
  files). Left open; if it recurs with a concrete repro it gets a fix
  and a regression test like everything else. → **It recurred with a
  concrete repro and was fixed in 0.3.3** (lone surrogate in the topic
  heading; the probes had aimed at the wrong input).
- Test suite: 48 → 52.

## 0.3.1 — 2026-10-14

Three bugs from the 0.3.0 field check — all in the new Behavior Memory
matching, all reproduced before fixing:

- **Brief dropped every warning on inflection mismatch.** Context
  matching was exact-word: "deploying" in the context never met "deploy"
  in the lesson, and a brief with a context returned `warnings=0` while
  the same store without a context returned the lesson. Matching now
  uses stemmed tokens on both sides — and, as a safety invariant,
  warnings can no longer drop to zero: when no lesson matches the
  context, the brief shows the most recent lessons and says so
  (`warnings_fallback` in the result).
- **Template prose could outscore real memories — with the ×3 lesson
  boost.** Search indexed every line of LESSONS.md, including the
  shipped template text (which naturally contains words like "facts",
  "search", "outrank"). In the root files (MEMORY.md, LESSONS.md,
  INTENTIONS.md) only bullet lines are memory entries, so only they are
  indexed now — the same entries-are-bullets doctrine `memory_forget`
  adopted in 0.3.0. Topic files keep full prose search.
- **Intentions fired on their action half.** Trigger matching ran over
  the whole `WHEN … → DO …` line, so a context mentioning "smoke suite"
  summoned a deploy intention. Intentions now match on the extracted
  WHEN trigger only.
- Test suite: 42 → 48, one regression class for the field report.

## 0.3.0 — 2026-10-14

**Behavior Memory** — a memory type the rest of the field doesn't have.
Competitors store facts (what the agent knows); 0.3.0 adds memory that
changes what the agent *does*:

- **`memory_learn` → LESSONS.md** — scar tissue: situation, what went
  wrong, the rule it taught. Lessons score ×3 in `memory_search` (they
  outrank equally-matching facts) and lead every brief.
- **`memory_intend` → INTENTIONS.md** — prospective memory:
  `WHEN <trigger> → DO <action>`, surfaced by situation rather than by
  search.
- **`memory_brief`** — the session-start pack in one call: warnings,
  intentions triggered by the brief's context argument, core facts, and
  recent activity, each line cited `file:line`.
- Search hits are now tagged by `kind` (fact / lesson / intention / log /
  topic); `memory_status` reports lesson and intention counts.
- `init` scaffolds the two new files; existing stores gain them on the
  next `init`/`learn`/`intend` call.
- Side effect worth noting: `memory_forget` now removes only bullet
  lines. Memory entries are bullets by construction; headings and prose
  scaffolding (including the new file templates, whose text mentions
  "memory_learn" etc.) can no longer be collateral damage of a forget.
- Test suite: 29 → 42 tests, including the full Behavior Memory flow
  over live MCP (learn in one call, intend in another, brief in a third
  surfaces both), newline-injection resistance for lesson fields, and
  lesson-over-fact ranking. demo.sh now teaches a fact, a lesson, and an
  intention in process 1 and briefs a fresh process 2.

## 0.2.2 — 2026-10-14

The two remaining server-killers, reported right after 0.2.1:

- **Deeply nested JSON.** A ~6 KB message nested thousands of levels
  could drive the JSON parser into `RecursionError` (the exact threshold
  is platform/C-stack dependent, which is why it reproduced on Windows
  but not in the Linux test environment). Messages are now depth-checked
  *before* parsing — bracket depth ignoring string contents, limit 100,
  far above any legitimate MCP message — and `RecursionError` is also
  caught around parsing and response serialization.
- **Invalid UTF-8 byte.** The 0.2.1 encoding fix traded silent corruption
  for a crash: a strict UTF-8 text reader decodes ahead in chunks, so one
  invalid byte raised `UnicodeDecodeError` during iteration and killed
  the server (taking already-buffered good messages with it). The server
  now reads the binary buffer and decodes **per line** with
  `errors="replace"`: a bad byte degrades to U+FFFD inside its own
  message and can never raise out of the read loop. A stray BOM at the
  start of a line is also tolerated now.
- Test suite: 25 → 29 tests, including both killer repros replayed
  against a live server, plus an adversarial fuzz pass (binary garbage,
  truncated JSON, 200 KB argument, CRLF) verified manually.

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
