#!/usr/bin/env bash
# Doorway MCP smoke test — Day 2b
#
# Usage: ./smoke_test.sh [base_url]
#   Default base_url: http://127.0.0.1:8000
#
# What this verifies:
#   - Server is reachable
#   - MCP initialize succeeds
#   - tools/list returns SEVEN tools (Day 2b adds give_item, receive_item,
#     end_conversation), each with "_meta" (underscore!), each pointing
#     at ui://widget/doorway-v7.html
#   - leave_milli is widget-only (ui.visibility = ["app"])
#   - approach_milli, milli_says, give_item, receive_item, end_conversation
#     are NOT widget-only — the model must be able to see them AND their
#     output. Hiding approach_milli in Day 2b v1 broke conversation: the
#     widget fired it fine but the brief (returned as visible text) never
#     reached the model, so it stayed in generic host voice.
#   - tools/call open_world returns structuredContent with mode, positions,
#     inventory (["wildflower"]), milli_line (null initially), last_outcome (null)
#   - tools/call approach_milli flips mode AND returns Milli's brief as
#     visible text (the model reads this and starts speaking as her)
#   - tools/call milli_says stores line + mood, returned in structuredContent
#   - tools/call give_item(wildflower, milli) removes wildflower from inventory
#   - tools/call receive_item(recipe_card, milli) adds recipe_card to inventory
#   - tools/call end_conversation stores outcome + flips mode back to world
#   - tools/call open_world AFTER end_conversation still shows last_outcome
#   - tools/call leave_milli clears milli_line and flips mode back to world
#   - resources/read for v7 returns mimeType: text/html+skybridge
#
# Notes:
#   - The smoke test does NOT supply openai/subject, so server-side state
#     all lands in the 'anonymous' bucket.
#   - milli_line + inventory + last_outcome are ephemeral (process-memory),
#     not Postgres. Server restarts reset them.

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

echo "[1/12] Health check"
curl -sS "$BASE/health" || echo "(health request failed)"
echo

hr
echo "[2/12] MCP initialize"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":1,"method":"initialize",
  "params":{"protocolVersion":"2025-06-18","capabilities":{},
            "clientInfo":{"name":"smoke","version":"0"}}
}'
echo

hr
echo "[3/12] tools/list"
echo "  Expect SEVEN tools:"
echo "    open_world, approach_milli, milli_says,"
echo "    give_item, receive_item, end_conversation, leave_milli"
echo "  Each with \"_meta\" (underscore!) and openai/outputTemplate = ui://widget/doorway-v7.html"
echo "  leave_milli should have ui.visibility = [\"app\"]"
echo "  approach_milli, milli_says, give_item, receive_item, end_conversation should NOT have ui.visibility"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":2,"method":"tools/list"
}'
echo

hr
echo "[4/12] tools/call open_world  (initial — expect mode:world, inventory:[wildflower], milli_line:null, last_outcome:null)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"open_world","arguments":{}}
}'
echo

hr
echo "[5/12] tools/call approach_milli  (expect mode:in_conversation_with_milli)"
echo "       Visible text should contain Milli's brief — 'You are Milli.' etc."
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":4,"method":"tools/call",
  "params":{"name":"approach_milli","arguments":{}}
}'
echo

hr
echo "[6/12] tools/call milli_says  (expect milli_line stored in structuredContent)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":5,"method":"tools/call",
  "params":{"name":"milli_says","arguments":{"line":"Track mud in and I will make you sweep it.","mood":"dry"}}
}'
echo

hr
echo "[7/12] tools/call give_item  (player → milli, wildflower)"
echo "       Expect inventory:[] — wildflower removed."
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":6,"method":"tools/call",
  "params":{"name":"give_item","arguments":{"item_id":"wildflower","to":"milli"}}
}'
echo

hr
echo "[8/12] tools/call receive_item  (milli → player, recipe_card)"
echo "       Expect inventory:[\"recipe_card\"] — recipe_card added."
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":7,"method":"tools/call",
  "params":{"name":"receive_item","arguments":{"item_id":"recipe_card","from":"milli"}}
}'
echo

hr
echo "[9/12] tools/call milli_says  (closing line before end_conversation)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":8,"method":"tools/call",
  "params":{"name":"milli_says","arguments":{"line":"Come back when the bread is out.","mood":"warm"}}
}'
echo

hr
echo "[10/12] tools/call end_conversation  (expect mode:world, last_outcome stored)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":9,"method":"tools/call",
  "params":{"name":"end_conversation","arguments":{"outcome":{
      "mood_after":"opened",
      "conversation_summary":"They brought me a wildflower. I gave them my mother'\''s biscuit recipe. I didn'\''t expect that.",
      "promises_from_player":["come back tomorrow"],
      "promises_to_player":[],
      "relationship_delta":1
  }}}
}'
echo

hr
echo "[11/12] tools/call open_world AGAIN  (PERSISTENCE — expect inventory:[recipe_card], last_outcome still there, mode:world)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":10,"method":"tools/call",
  "params":{"name":"open_world","arguments":{}}
}'
echo

hr
echo "[12/12] resources/read  (expect mimeType: text/html+skybridge, v7 widget)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":11,"method":"resources/read",
  "params":{"uri":"ui://widget/doorway-v7.html"}
}'
echo

hr
echo "Done. Visually verify above:"
echo "  * tools/list shows ALL SEVEN tools, each with \"_meta\" (underscore)"
echo "  * openai/outputTemplate matches ui://widget/doorway-v7.html exactly"
echo "  * approach_milli + leave_milli have ui.visibility: [\"app\"]"
echo "  * milli_says + give_item + receive_item + end_conversation NOT hidden"
echo "  * call 4 (open_world) returns inventory:[\"wildflower\"], last_outcome:null"
echo "  * call 5 (approach_milli) visible text contains the brief"
echo "  * call 6 (milli_says) returns milli_line:\"Track mud in...\", mood:\"dry\""
echo "  * call 7 (give_item) returns inventory:[] (wildflower gone)"
echo "  * call 8 (receive_item) returns inventory:[\"recipe_card\"]"
echo "  * call 10 (end_conversation) returns mode:\"world\", last_outcome populated,"
echo "                               milli_line:null"
echo "  * call 11 (open_world) still shows last_outcome.mood_after=\"opened\","
echo "                         inventory:[\"recipe_card\"], mode:\"world\""
echo "  * resources/read returns mimeType: \"text/html+skybridge\""
hr
