#!/usr/bin/env bash
# Doorway MCP smoke test
#
# Usage: ./smoke_test.sh [base_url]
#   Default base_url: http://127.0.0.1:8000
#
# What this verifies (matches CHATGPT_APP_HANDOVER.md section "Testing
# without ChatGPT"):
#   - Server is reachable
#   - MCP initialize succeeds
#   - tools/list returns "_meta" with underscore (not "meta")
#   - tool _meta has openai/outputTemplate matching the widget URI
#   - resources/read returns mimeType: text/html+skybridge
#   - Widget _meta has CSP under both ui.csp.* and openai/widgetCSP.*
#
# If any step fails, fix locally before pushing to Railway — ChatGPT errors
# are much harder to debug than curl errors.

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

echo "[1/6] Health check"
curl -sS "$BASE/health" || echo "(health request failed)"
echo

hr
echo "[2/6] MCP initialize"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":1,"method":"initialize",
  "params":{"protocolVersion":"2025-06-18","capabilities":{},
            "clientInfo":{"name":"smoke","version":"0"}}
}'
echo

hr
echo "[3/6] tools/list  (expect _meta WITH underscore, openai/outputTemplate = ui://widget/doorway-v1.html)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":2,"method":"tools/list"
}'
echo

hr
echo "[4/6] tools/call open_world  (expect structuredContent with status: ok)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"open_world","arguments":{}}
}'
echo

hr
echo "[5/6] resources/list"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":4,"method":"resources/list"
}'
echo

hr
echo "[6/6] resources/read  (expect mimeType: text/html+skybridge, CSP in _meta)"
curl -sS -X POST "$BASE/mcp/" "${HDRS[@]}" -d '{
  "jsonrpc":"2.0","id":5,"method":"resources/read",
  "params":{"uri":"ui://widget/doorway-v1.html"}
}'
echo

hr
echo "Done. Visually verify above:"
echo "  * tools/list shows \"_meta\"   (underscore, not \"meta\")"
echo "  * openai/outputTemplate matches ui://widget/doorway-v1.html exactly"
echo "  * tools/call returns structuredContent: {status: \"ok\", ...}"
echo "  * resources/read returns mimeType: \"text/html+skybridge\""
echo "  * widget _meta has both ui.csp.* AND openai/widgetCSP.* keys"
hr
