#!/usr/bin/env bash
# Doorway MCP smoke test — Day 2a
#
# Usage: ./smoke_test.sh [base_url]
#   Default base_url: http://127.0.0.1:8000
#
# What this verifies:
#   - Server is reachable
#   - MCP initialize succeeds
#   - tools/list returns FOUR tools (added milli_says for Day 2a), each
#     with "_meta" (underscore!), each pointing at ui://widget/doorway-v6.html
#   - approach_milli and leave_milli are widget-only (ui.visibility = ["app"])
#   - milli_says is NOT widget-only — the model must be able to call it
#   - tools/call open_world returns structuredContent with mode, positions,
#     inventory (["wildflower"]), milli_line (null initially)
#   - tools/call approach_milli flips mode AND returns Milli's brief as
#     visible text (the model reads this and starts speaking as her)
#   - tools/call milli_says stores line + mood, returned in structuredContent
#   - tools/call open_world AFTER milli_says shows the stored line
#   - tools/call leave_milli clears milli_line and flips mode back to world
#   - resources/read for v6 returns mimeType: text/html+skybridge
#
# Notes:
#   - The smoke test does NOT supply openai/subject, so server-side state
#     all lands in the 'anonymous' bucket.
#   - milli_line + inventory are ephemeral (process-memory), not Postgres.
#     Server restarts reset them. Day 2b migrates inventory into Postgres.

set -u

BASE="${1:-http://127.0.0.1:8000}"
HDRS=(
  -H "Content-Type: application/json"
  -H "Accept: application/json, text/event-stream"
  -H "MCP-Protocol-Version: 2025-06-18"
)

hr() { printf '\n%s\n' "------------------------------------------------------------"; }

hr
echo "Target: $BASE"
hr

echo "[1/9] Health check"
curl -sS "$BASE/health" || echo "(health request failed)"
echo

hr
echo "[2/9] MCP initialize"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":1,"method":"initialize",
  "params":{"protocolVersion":"2025-06-18","capabilities":{},
            "clientInfo":{"name":"smoke","version":"0"}}
}'
echo

hr
echo "[3/9] tools/list"
echo "  Expect FOUR tools: open_world, approach_milli, milli_says, leave_milli"
echo "  Each with \"_meta\" (underscore!) and openai/outputTemplate = ui://widget/doorway-v6.html"
echo "  approach_milli + leave_milli should have ui.visibility = [\"app\"]"
echo "  milli_says should NOT have ui.visibility — model must be able to call it"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":2,"method":"tools/list"
}'
echo

hr
echo "[4/9] tools/call open_world  (initial — expect mode:world, inventory:[wildflower], milli_line:null)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"open_world","arguments":{}}
}'
echo

hr
echo "[5/9] tools/call approach_milli  (expect mode:in_conversation_with_milli)"
echo "      Visible text should contain Milli's brief — 'You are Milli.' etc."
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":4,"method":"tools/call",
  "params":{"name":"approach_milli","arguments":{}}
}'
echo

hr
echo "[6/9] tools/call milli_says  (expect milli_line stored in structuredContent)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":5,"method":"tools/call",
  "params":{"name":"milli_says","arguments":{"line":"Track mud in and I will make you sweep it.","mood":"dry"}}
}'
echo

hr
echo "[7/9] tools/call open_world AGAIN  (PERSISTENCE — expect line still there)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":6,"method":"tools/call",
  "params":{"name":"open_world","arguments":{}}
}'
echo

hr
echo "[8/9] tools/call leave_milli  (expect mode:world, milli_line:null)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":7,"method":"tools/call",
  "params":{"name":"leave_milli","arguments":{}}
}'
echo

hr
echo "[9/9] resources/read  (expect mimeType: text/html+skybridge, CSP in _meta)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":8,"method":"resources/read",
  "params":{"uri":"ui://widget/doorway-v6.html"}
}'
echo

hr
echo "Done. Visually verify above:"
echo "  * tools/list shows ALL FOUR tools, each with \"_meta\" (underscore)"
echo "  * openai/outputTemplate matches ui://widget/doorway-v6.html exactly"
echo "  * approach_milli + leave_milli have ui.visibility: [\"app\"]"
echo "  * milli_says is NOT hidden from the model"
echo "  * call 4 (open_world) returns inventory:[\"wildflower\"], milli_line:null"
echo "  * call 5 (approach_milli) visible text contains the brief"
echo "  * call 6 (milli_says) returns milli_line:\"Track mud in...\", mood:\"dry\""
echo "  * call 7 (open_world) ALSO returns the same line — ephemeral state holds"
echo "  * call 8 (leave_milli) returns mode:\"world\", milli_line:null"
echo "  * resources/read returns mimeType: \"text/html+skybridge\""
hr
