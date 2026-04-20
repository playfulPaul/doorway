#!/usr/bin/env bash
# Doorway MCP smoke test — Day 1
#
# Usage: ./smoke_test.sh [base_url]
#   Default base_url: http://127.0.0.1:8000
#
# What this verifies:
#   - Server is reachable
#   - MCP initialize succeeds
#   - tools/list returns the three Day 1 tools, each with "_meta"
#     (with underscore!), each pointing at ui://widget/doorway-v2.html
#   - approach_milli and leave_milli are widget-only (ui.visibility = ["app"])
#   - tools/call open_world returns structuredContent with mode + positions
#   - tools/call approach_milli flips mode to in_conversation_with_milli
#   - tools/call open_world AFTER approach proves state persisted
#     (the Day 1 gate test, in CLI form)
#   - tools/call leave_milli flips mode back to world
#   - resources/read for v2 returns mimeType: text/html+skybridge
#
# Notes:
#   - The smoke test does NOT supply openai/subject, so server-side state
#     all lands in the 'anonymous' bucket. That's fine — it lets us
#     observe state transitions without having to fake a subject.
#   - With DATABASE_URL set, state persists across server restarts. Without
#     it, state lives in process memory and resets when uvicorn restarts.

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

echo "[1/8] Health check"
curl -sS "$BASE/health" || echo "(health request failed)"
echo

hr
echo "[2/8] MCP initialize"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":1,"method":"initialize",
  "params":{"protocolVersion":"2025-06-18","capabilities":{},
            "clientInfo":{"name":"smoke","version":"0"}}
}'
echo

hr
echo "[3/8] tools/list"
echo "  Expect THREE tools: open_world, approach_milli, leave_milli"
echo "  Each with \"_meta\" (underscore!) and openai/outputTemplate = ui://widget/doorway-v2.html"
echo "  approach_milli + leave_milli should also have ui.visibility = [\"app\"]"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":2,"method":"tools/list"
}'
echo

hr
echo "[4/8] tools/call open_world  (initial — expect mode: world)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"open_world","arguments":{}}
}'
echo

hr
echo "[5/8] tools/call approach_milli  (expect mode: in_conversation_with_milli)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":4,"method":"tools/call",
  "params":{"name":"approach_milli","arguments":{}}
}'
echo

hr
echo "[6/8] tools/call open_world AGAIN  (PERSISTENCE TEST — expect mode STILL in_conversation_with_milli)"
echo "      This is Day 1's gate condition expressed in curl: state survives between tool calls."
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":5,"method":"tools/call",
  "params":{"name":"open_world","arguments":{}}
}'
echo

hr
echo "[7/8] tools/call leave_milli  (expect mode: world)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":6,"method":"tools/call",
  "params":{"name":"leave_milli","arguments":{}}
}'
echo

hr
echo "[8/8] resources/read  (expect mimeType: text/html+skybridge, CSP in _meta)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":7,"method":"resources/read",
  "params":{"uri":"ui://widget/doorway-v2.html"}
}'
echo

hr
echo "Done. Visually verify above:"
echo "  * tools/list shows all three tools, each with \"_meta\" (underscore)"
echo "  * openai/outputTemplate matches ui://widget/doorway-v2.html exactly"
echo "  * approach_milli + leave_milli have ui.visibility: [\"app\"]"
echo "  * open_world (call 4) returns mode: \"world\""
echo "  * approach_milli (call 5) returns mode: \"in_conversation_with_milli\""
echo "  * open_world (call 6) ALSO returns mode: \"in_conversation_with_milli\"  <-- persistence!"
echo "  * leave_milli (call 7) returns mode: \"world\""
echo "  * resources/read returns mimeType: \"text/html+skybridge\""
hr
