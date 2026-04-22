#!/usr/bin/env bash
# Doorway MCP smoke test — Day 3b (today)
#
# Usage: ./smoke_test.sh [base_url]
#   Default base_url: http://127.0.0.1:8000
#
# What this verifies:
#   - Server is reachable
#   - MCP initialize succeeds
#   - tools/list returns SEVEN tools, each with "_meta" (underscore!), each
#     pointing at ui://widget/doorway-v7.html
#   - leave_milli is widget-only (ui.visibility = ["app"])
#   - approach_milli, milli_says, give_item, receive_item, end_conversation
#     are NOT widget-only — the model must be able to see them AND their
#     output.
#   - tools/call open_world returns structuredContent with mode, positions,
#     inventory (["wildflower"]), milli_line (null initially), last_outcome (null)
#   - tools/call approach_milli flips mode AND returns Milli's brief as
#     visible text. On first contact the brief's "What you remember about
#     them" section reads "Nothing specific..." (memory empty).
#   - tools/call milli_says stores line + mood, returned in structuredContent
#   - tools/call give_item(wildflower, milli) removes wildflower from inventory
#   - tools/call receive_item(recipe_card, milli) adds recipe_card to inventory
#   - tools/call end_conversation stores outcome (ephemeral card) AND
#     appends to the persistent conversation log (Day 3a)
#   - tools/call open_world AFTER end_conversation still shows last_outcome
#   - tools/call approach_milli AGAIN after a close returns a brief whose
#     "What you remember about them" section quotes the prior
#     conversation_summary — Milli is reading her own memory.
#   - resources/read for v7 returns mimeType: text/html+skybridge
#
# Notes:
#   - The smoke test does NOT supply openai/subject, so server-side state
#     all lands in the 'anonymous' bucket.
#   - milli_line + inventory + last_outcome are ephemeral (process-memory),
#     not Postgres. Server restarts reset them.
#   - The conversation_outcomes log is process-memory locally (no
#     DATABASE_URL) and Postgres in prod. Either way it's what the Day 3a
#     memory test below reads back.

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

echo "[1/13] Health check"
curl -sS "$BASE/health" || echo "(health request failed)"
echo

hr
echo "[2/13] MCP initialize"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":1,"method":"initialize",
  "params":{"protocolVersion":"2025-06-18","capabilities":{},
            "clientInfo":{"name":"smoke","version":"0"}}
}'
echo

hr
echo "[3/13] tools/list"
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
echo "[4/13] tools/call open_world  (initial — expect mode:world, inventory:[wildflower], milli_line:null, last_outcome:null)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"open_world","arguments":{}}
}'
echo

hr
echo "[5/13] tools/call approach_milli  (expect mode:in_conversation_with_milli)"
echo "       Visible text should contain Milli's brief — 'You are Milli.' etc."
echo "       Day 3b: brief should contain a '## Today in your kitchen' section,"
echo "               with 'Wednesday, the third week', 'sourdough', 'rosemary',"
echo "               'Elna', and a '## How your day enters the conversation'"
echo "               rule block. Memory section still reads 'Nothing specific...'"
echo "               on first contact."
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":4,"method":"tools/call",
  "params":{"name":"approach_milli","arguments":{}}
}'
echo

hr
echo "[6/13] tools/call milli_says  (expect milli_line stored in structuredContent)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":5,"method":"tools/call",
  "params":{"name":"milli_says","arguments":{"line":"Track mud in and I will make you sweep it.","mood":"dry"}}
}'
echo

hr
echo "[7/13] tools/call give_item  (player → milli, wildflower)"
echo "       Expect inventory:[] — wildflower removed."
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":6,"method":"tools/call",
  "params":{"name":"give_item","arguments":{"item_id":"wildflower","to":"milli"}}
}'
echo

hr
echo "[8/13] tools/call receive_item  (milli → player, recipe_card)"
echo "       Expect inventory:[\"recipe_card\"] — recipe_card added."
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":7,"method":"tools/call",
  "params":{"name":"receive_item","arguments":{"item_id":"recipe_card","from":"milli"}}
}'
echo

hr
echo "[9/13] tools/call milli_says  (closing line before end_conversation)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":8,"method":"tools/call",
  "params":{"name":"milli_says","arguments":{"line":"Come back when the bread is out.","mood":"warm"}}
}'
echo

hr
echo "[10/13] tools/call end_conversation  (expect mode:world, last_outcome stored)"
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
echo "[11/13] tools/call open_world AGAIN  (PERSISTENCE — expect inventory:[recipe_card], last_outcome still there, mode:world)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":10,"method":"tools/call",
  "params":{"name":"open_world","arguments":{}}
}'
echo

hr
echo "[12/13] tools/call approach_milli AGAIN  (MEMORY — Day 3a)"
echo "       The returned visible text is the brief. Look for:"
echo "         - A '## What you remember about them' heading"
echo "         - The exact summary from call 10:"
echo "             'They brought me a wildflower. I gave them my mother'\''s"
echo "              biscuit recipe. I didn'\''t expect that.'"
echo "         - A 'complete record' / 'do not invent' guardrail phrase"
echo "       If the brief says 'Nothing specific' here, memory isn'\''t"
echo "       flowing from log → brief."
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":12,"method":"tools/call",
  "params":{"name":"approach_milli","arguments":{}}
}'
echo

hr
echo "[13/13] resources/read  (expect mimeType: text/html+skybridge, v7 widget)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":13,"method":"resources/read",
  "params":{"uri":"ui://widget/doorway-v7.html"}
}'
echo

hr
echo "Done. Visually verify above:"
echo "  * tools/list shows ALL SEVEN tools, each with \"_meta\" (underscore)"
echo "  * openai/outputTemplate matches ui://widget/doorway-v7.html exactly"
echo "  * ONLY leave_milli has ui.visibility: [\"app\"]"
echo "  * approach_milli, milli_says, give_item, receive_item, end_conversation NOT hidden"
echo "  * call 4 (open_world) returns inventory:[\"wildflower\"], last_outcome:null"
echo "  * call 5 (approach_milli) visible text contains the brief, including:"
echo "                            - \"## Today in your kitchen\""
echo "                            - \"Wednesday, the third week\""
echo "                            - \"sourdough\", \"rosemary\", \"Elna\""
echo "                            - \"## How your day enters the conversation\""
echo "                            - \"What you remember\" reads 'Nothing specific...'"
echo "  * call 6 (milli_says) returns milli_line:\"Track mud in...\", mood:\"dry\""
echo "  * call 7 (give_item) returns inventory:[] (wildflower gone)"
echo "  * call 8 (receive_item) returns inventory:[\"recipe_card\"]"
echo "  * call 10 (end_conversation) returns mode:\"world\", last_outcome populated,"
echo "                               milli_line:null"
echo "  * call 11 (open_world) still shows last_outcome.mood_after=\"opened\","
echo "                         inventory:[\"recipe_card\"], mode:\"world\""
echo "  * call 12 (approach_milli AGAIN) brief now includes a \"What you"
echo "                                   remember\" section quoting the exact"
echo "                                   conversation_summary from call 10"
echo "                                   — this is the Day 3a memory loop."
echo "  * resources/read returns mimeType: \"text/html+skybridge\""
hr
