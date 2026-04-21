"""
Doorway MCP Server — POC (Day 1: world + mode flip, no chat yet).

Day 1 introduces three tools and one widget:

  - open_world (model-callable): launches/resumes the experience. Reads
    the player's stored mode + position, returns full world state for the
    widget to render. If the player was last seen mid-conversation with
    Milli, they resume in conversation mode — that's the persistence test.

  - approach_milli (widget-only): the widget calls this when the player
    taps Milli. Flips mode to in_conversation_with_milli, snaps the player
    to the spot beside her.

  - leave_milli (widget-only): called from the conversation placeholder's
    Leave button. Flips mode back to world.

State of record lives in Postgres (or in-memory for local dev). The widget
is a dumb renderer — it never holds load-bearing state. See state.py and
CHATGPT_APP_HANDOVER.md (the hybrid pattern section).

Critical platform details (do not relax without re-reading the handover):
  - Tool/resource _meta uses kwarg `_meta=` (with underscore) so pydantic
    serializes as "_meta" on the wire.
  - Resource MIME type is "text/html+skybridge".
  - ui.resourceUri + openai/outputTemplate point to the same widget URI.
  - CSP set both as ui.csp.* (MCP standard) and openai/widgetCSP.* (OpenAI).
  - approach_milli / leave_milli are widget-only via ui.visibility = ["app"]
    AND openai/widgetAccessible = True, so the widget can fire them and
    the model can't.
  - Widget URI is bumped from v1 → v2 because the HTML changed materially;
    cache-bust discipline requires bumping AND renaming the file.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Optional

from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Resource, TextContent, Tool
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import state

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Bump the -vN suffix on every widget HTML change. ChatGPT caches widgets
# by URI; bumping is the cheapest cache-bust.
#   v1 = Day 0 handshake
#   v2 = Day 1 world + conversation placeholder (initial build)
#   v3 = Day 1 interaction fix: widget-initiated tool calls weren't
#        re-rendering because ChatGPT doesn't reliably push toolOutput
#        updates for widget-initiated calls the way it does for model
#        calls. v3 uses callTool's return value + optimistic local flip.
#   v4 = PIP pinning. Widget requests picture-in-picture on load so the
#        game stays a single persistent window and chats flow underneath.
WIDGET_URI = "ui://widget/doorway-v4.html"
WIDGET_PATH = Path(__file__).parent / "widgets" / "doorway_v4.html"

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = Server("doorway")


# Iron rule embedded in every tool description so the model doesn't drift.
# Per the handover doc: short, imperative, ALL CAPS for the rule, no apology.
IRON_RULE = (
    "THE WIDGET IS THE GAME. DO NOT NARRATE THE WIDGET CONTENTS, DO NOT "
    "DESCRIBE WHAT THE PLAYER SEES, DO NOT OFFER STRATEGY. The widget is "
    "self-contained; the player interacts with it directly."
)


def _current_subject() -> Optional[str]:
    """Pull openai/subject from the current MCP request, if present.

    Defensive: SDK shape varies between versions and dev-mode connectors
    sometimes don't supply it. Returning None is fine — state.py falls
    back to an 'anonymous' bucket so local testing still works.
    """
    try:
        ctx = mcp.request_context
        meta = getattr(ctx, "meta", None)
        if meta is None:
            return None
        if isinstance(meta, dict):
            return meta.get("openai/subject")
        if hasattr(meta, "model_dump"):
            return meta.model_dump(by_alias=True).get("openai/subject")
    except Exception:
        pass
    return None


def _world_payload(player: dict, last_action: str) -> dict:
    """Shape the structuredContent the widget renders from.

    Keep this stable across tools — the widget reads from a single shape
    no matter which tool produced the latest result.
    """
    return {
        "mode": player["mode"],
        "player_position": player["position"],
        "milli_position": state.MILLI_POSITION,
        "room": state.ROOM,
        "last_action": last_action,
        "phase": "day_1",
    }


# ---------------------------------------------------------------------------
# Tool list
# ---------------------------------------------------------------------------

@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="open_world",
            description=(
                "Open the Doorway game world. Call this when the player asks "
                "to start, open, resume, or play Doorway (or 'Harvest Town', "
                "or just gestures at the game). " + IRON_RULE
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            _meta={
                "ui.resourceUri": WIDGET_URI,
                "openai/outputTemplate": WIDGET_URI,
                "openai/toolInvocation/invoking": "",
                "openai/toolInvocation/invoked": "",
                # Allow the widget itself to call the other tools.
                "openai/widgetAccessible": True,
            },
        ),
        Tool(
            name="approach_milli",
            description=(
                "Player walks up to Milli to start a conversation. "
                "Widget-only — fires when the player taps Milli."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            _meta={
                "ui.resourceUri": WIDGET_URI,
                "openai/outputTemplate": WIDGET_URI,
                "openai/toolInvocation/invoking": "",
                "openai/toolInvocation/invoked": "",
                "openai/widgetAccessible": True,
                # Hide from the model — the widget drives this.
                "ui.visibility": ["app"],
            },
        ),
        Tool(
            name="leave_milli",
            description=(
                "Player steps away from Milli, returning to the room. "
                "Widget-only — fires when the player presses Leave in the "
                "conversation view."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            _meta={
                "ui.resourceUri": WIDGET_URI,
                "openai/outputTemplate": WIDGET_URI,
                "openai/toolInvocation/invoking": "",
                "openai/toolInvocation/invoked": "",
                "openai/widgetAccessible": True,
                "ui.visibility": ["app"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> tuple[list[TextContent], dict]:
    subject = _current_subject()

    if name == "open_world":
        player = await state.get_or_create_player(subject)
        structured = _world_payload(player, last_action="open_world")
        # Visible text is what shows in the chat transcript next to the
        # widget. Keep it minimal — the widget is the experience.
        visible = TextContent(type="text", text="Doorway opened.")
        return [visible], structured

    if name == "approach_milli":
        player = await state.update_player(
            subject,
            mode="in_conversation_with_milli",
            position=state.PLAYER_AT_MILLI,
        )
        structured = _world_payload(player, last_action="approach_milli")
        visible = TextContent(type="text", text="")
        return [visible], structured

    if name == "leave_milli":
        # Step the player back to a spot just past Milli's left, so the
        # transition out feels physical rather than a teleport.
        step_back = {"x": 60, "y": 50}
        player = await state.update_player(
            subject,
            mode="world",
            position=step_back,
        )
        structured = _world_payload(player, last_action="leave_milli")
        visible = TextContent(type="text", text="")
        return [visible], structured

    raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Resources (the widget itself)
# ---------------------------------------------------------------------------

@mcp.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri=AnyUrl(WIDGET_URI),
            name="Doorway Widget v4",
            description="Doorway POC widget — Day 1 (world + conversation placeholder).",
            mimeType="text/html+skybridge",
            _meta={
                # Day 1 widget is self-contained; no CDN fetches.
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
    async with session_manager.run():
        yield


async def handle_mcp(scope, receive, send):
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
