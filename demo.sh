#!/usr/bin/env bash
# Agent Memory demo: a fact saved in one process is recalled by a
# brand-new process — the amnesia cure, in 20 seconds.
set -euo pipefail
cd "$(dirname "$0")"
STORE="$(mktemp -d)/memory"
trap 'rm -rf "$(dirname "$STORE")"' EXIT

echo "== Process 1: a fresh agent learns something =="
python3 agent_memory.py --store "$STORE" init >/dev/null
python3 agent_memory.py --store "$STORE" save "Andrew's agency is called We Are 239 and it serves Southwest Florida roofers"
python3 agent_memory.py --store "$STORE" log "Demo: saved the agency fact"

echo
echo "== Process 2: a DIFFERENT fresh process — what do you remember? =="
python3 agent_memory.py --store "$STORE" search "what is Andrew's agency"

echo
echo "== The store itself — plain markdown you can open and edit =="
find "$STORE" -type f | sort
echo
echo "Done. Same store works for any MCP agent: see README.md."
