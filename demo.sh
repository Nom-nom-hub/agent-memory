#!/usr/bin/env bash
# Agent Memory demo: a fact, a LESSON, and an INTENTION saved in one
# process are all picked up by a brand-new process — the amnesia cure,
# in 20 seconds.
set -euo pipefail
cd "$(dirname "$0")"
STORE="$(mktemp -d)/memory"
trap 'rm -rf "$(dirname "$STORE")"' EXIT

echo "== Process 1: a fresh agent learns something =="
python3 agent_memory.py --store "$STORE" init >/dev/null
python3 agent_memory.py --store "$STORE" save "Andrew's agency is called We Are 239 and it serves Southwest Florida roofers"
python3 agent_memory.py --store "$STORE" learn --situation "writing outreach drafts" --went-wrong "signed as Designs By Teck and got corrected" --rule "always sign as Andrew with We Are 239"
python3 agent_memory.py --store "$STORE" intend --when "writing outreach" --do "check the lesson list before drafting"
python3 agent_memory.py --store "$STORE" log "Demo: saved the agency fact, a lesson, and an intention"

echo
echo "== Process 2: a DIFFERENT fresh process — search recalls the fact =="
python3 agent_memory.py --store "$STORE" search "what is Andrew's agency"

echo
echo "== Process 2 opens with a brief for outreach work =="
python3 agent_memory.py --store "$STORE" brief "writing outreach drafts for a new lead"

echo
echo "== The store itself — plain markdown you can open and edit =="
find "$STORE" -type f | sort
echo
echo "Done. Same store works for any MCP agent: see README.md."
