"""
Doorway MCP Server — POC (Day 0 scaffolding).

A single placeholder tool that opens the widget. The widget shows a Day 0
handshake message to prove the platform plumbing works end-to-end before
we start building the actual game.

Built on the patterns from CHATGPT_APP_HANDOVER.md. The critical details:

- Tool _meta uses kwarg `_meta=` (with underscore) so pydantic serializes
  as "_meta" on the wire. Using `meta=` silently strips the metadata.
- Resource MIME type is "text/html+skybridge", not "text/html", so ChatGPT
  injects the window.openai bridge.
- ui.resourceUri + openai/outputTemplate point to the same URI — set both.
- CSP set both as ui.csp.* (MCP standard) and openai/widgetCSP.* (OpenAI compat).
- @mcp.read_resource compares with str(uri), not uri directly.
- StreamableHTTPSessionManager lives in streamable_http_manager, not streamable_http.
- Mount /mcp as a raw ASGI callable (scope, receive, send), not a Starlette handler.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Resource, TextContent, Tool
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Bump the -vN suffix on every widget HTML change — ChatGPT aggressively caches
# widgets by URI, and a bump is the cheapest way to force a refresh.
WIDGET_URI = "ui://widget/doorway-v1.html"
WIDGET_PATH = Path(__file__).parent / "widgets" / "doorway_v1.html"

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = Server("doorway")


@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="open_world",
            description=(
                "Open the Doorway game world. Call this when the player wants "
                "to start or resume playing Doorway. THE WIDGET IS THE GAME — "
                "do not describe what's happening in the widget to the user."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            _meta={
                # Widget URI — set both MCP standard and OpenAI compat keys.
                "ui.resourceUri": WIDGET_URI,
                "openai/outputTemplate": WIDGET_URI,
                # Empty invocation strings so ChatGPT doesn't chatter during calls.
                "openai/toolInvocation/invoking": "",
                "openai/toolInvocation/invoked": "",
                # Allow the widget itself to call tools (needed Day 2+).
                "openai/widgetAccessible": True,
            },
        ),
    ]


@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> tuple[list[TextContent], dict]:
    if name == "open_world":
        # Day 0: a simple handshake payload so the widget has something to
        # render. Real world state arrives on Day 1.
        structured = {
            "status": "ok",
            "phase": "day_0",
            "message": "Doorway Day 0 handshake successful.",
        }
        visible = TextContent(type="text", text="Doorway opened.")
        return [visible], structured

    raise ValueError(f"Unknown tool: {name}")


@mcp.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri=AnyUrl(WIDGET_URI),
            name="Doorway Widget v1",
            description="Doorway POC widget — Day 0 handshake placeholder.",
            mimeType="text/html+skybridge",
            _meta={
                # CSP keys — dual-written for MCP standard + OpenAI compat.
                # Day 0 widget is fully self-contained (no CDN), so empty arrays.
                "ui.csp.connectDomains": [],
                "ui.csp.resourceDomains": [],
                "openai/widgetCSP.connect_domains": [],
                "openai/widgetCSP.resource_domains": [],
                "ui.prefersBorder": True,
                "openai/widgetPrefersBorder": True,
                "openai/widgetDescription": "The Doorway game world.",
            },
        ),
    ]


@mcp.read_resource()
async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
    # Always compare str(uri) — the pydantic AnyUrl doesn't compare cleanly
    # against a string literal otherwise.
    if str(uri) == WIDGET_URI:
        html = WIDGET_PATH.read_text(encoding="utf-8")
        return [ReadResourceContents(content=html, mime_type="text/html+skybridge")]

    raise ValueError(f"Unknown resource: {uri}")


# ---------------------------------------------------------------------------
# HTTP transport (Starlette + StreamableHTTP)
# ---------------------------------------------------------------------------

session_manager = StreamableHTTPSessionManager(app=mcp, stateless=True)


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    # Required: the session manager is an async context manager, not a
    # startup handler. Forgetting this raises a cryptic error on first request.
    async with session_manager.run():
        yield


async def handle_mcp(scope, receive, send):
    # ASGI-style callable (scope, receive, send) — not a Starlette Request
    # handler. The session manager's handle_request IS ASGI.
    await session_manager.handle_request(scope, receive, send)


async def handle_health(_request):
    return JSONResponse({"status": "ok", "service": "doorway"})


app = Starlette(
    routes=[
        Route("/health", handle_health),
        Mount("/mcp", app=handle_mcp),
    ],
    lifespan=lifespan,
)
