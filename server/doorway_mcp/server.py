"""
Doorway MCP Server — POC (Day 2a: real conversation voice, no items yet).

Day 2a extends Day 1 with actual conversation. The architectural call here:
Milli's lines live *inside the widget*, not in the chat. The chat is where
the player types TO her; the widget is where she IS. This is the whole
"doorway" question — does she feel like she lives somewhere?

Tools:

  - open_world (model-callable): launches/resumes the experience. Reads
    stored mode + position + ephemeral conversation state, returns the
    full payload for the widget. Persistence test carried over from Day 1.

  - approach_milli (widget-only): fires when the player taps Milli. Flips
    mode to in_conversation_with_milli AND returns Milli's host-instruction
    brief as visible text — so the model immediately starts acting as her.
    Clears any leftover milli_line so the next conversation opens clean.

  - milli_says (model-callable AND widget-accessible): how Milli speaks.
    Every line she says goes through this. Takes (line, mood); stores the
    line; widget renders it inside the conversation panel. Iron rule in
    her brief: she must NEVER write text in chat — only tool calls. If
    playtest shows drift, tighten the brief and the tool description.

  - leave_milli (widget-only): step-away button. Flips mode back to world,
    wipes milli_line so next visit starts fresh.

State of record for persistent fields (mode + position) lives in Postgres.
Ephemeral fields (inventory, milli_line, milli_mood) live in process memory
for now — Day 2b will migrate inventory into the DB when give_item lands.

Critical platform details (do not relax without re-reading the handover):
  - Tool/resource _meta uses kwarg `_meta=` (with underscore) so pydantic
    serializes as "_meta" on the wire.
  - Resource MIME type is "text/html+skybridge".
  - ui.resourceUri + openai/outputTemplate point to the same widget URI.
  - CSP set both as ui.csp.* (MCP standard) and openai/widgetCSP.* (OpenAI).
  - approach_milli / leave_milli are widget-only via ui.visibility = ["app"].
  - milli_says is NOT restricted to widget — the model MUST be able to call
    it. openai/widgetAccessible is also True so widget-initiated speech
    (e.g. quick replies) could work later without a server change.
  - Widget URI bumped on every HTML change for cache-bust discipline.
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

from . import milli as milli_module
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
#   v4 = PIP attempt #1 — broken. Called requestDisplayMode on mount via
#        setTimeout, which violates the browser's gesture-gated rule for
#        display-mode changes. Silent fail, stayed inline.
#   v5 = PIP attempt #2 — fixed. requestDisplayMode is now called
#        synchronously inside a one-shot pointerdown handler. First tap
#        on the widget = pin gesture. Argument shape is { mode: "pip" }
#        not "pip". See "user-gesture rule" in CHATGPT_APP_HANDOVER.md.
#   v6 = Day 2a — real conversation panel. Milli's latest line renders
#        inside the widget (structuredContent.milli_line), not in chat.
#        Inventory badge shows the wildflower. Player types in the
#        ChatGPT chat; widget owns Milli's side.
WIDGET_URI = "ui://widget/doorway-v6.html"
WIDGET_PATH = Path(__file__).parent / "widgets" / "doorway_v6.html"

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

# Rule specific to conversation mode. The model MUST speak only through
# milli_says — never in plain chat text. This is what makes Milli feel like
# she lives in the widget rather than being a chatbot.
CONVERSATION_RULE = (
    "WHEN MILLI SPEAKS, CALL THE milli_says TOOL. DO NOT WRITE TEXT IN CHAT. "
    "Every line she says MUST go through milli_says(line, mood). Plain text "
    "responses break the illusion that she lives in the kitchen."
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


def _world_payload(player: dict, ephemeral: dict, last_action: str) -> dict:
    """Shape the structuredContent the widget renders from.

    Keep this stable across tools — the widget reads from a single shape
    no matter which tool produced the latest result. Day 2a adds three
    fields: inventory (for the flower badge), milli_line (her latest
    spoken line), milli_mood (tone hint for styling).
    """
    return {
        "mode": player["mode"],
        "player_position": player["position"],
        "milli_position": state.MILLI_POSITION,
        "room": state.ROOM,
        "inventory": ephemeral.get("inventory", []),
        "milli_line": ephemeral.get("milli_line"),
        "milli_mood": ephemeral.get("milli_mood"),
        "last_action": last_action,
        "phase": "day_2a",
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
                "Widget-only — fires when the player taps Milli. "
                "The tool result contains Milli's character brief: after "
                "it fires, YOU ARE MILLI. Immediately call milli_says with "
                "your first line. " + CONVERSATION_RULE
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
            name="milli_says",
            description=(
                "Milli speaks. This is HOW she speaks — every line she says "
                "MUST go through this tool. Never write Milli's dialogue as "
                "plain text in chat. `line` is what she says, first-person, "
                "in her voice. `mood` is one of: warm, dry, curious, "
                "guarded, amused, quiet. " + CONVERSATION_RULE
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "line": {
                        "type": "string",
                        "description": (
                            "The exact line Milli says, first-person, in her "
                            "voice. Usually one sentence; two if the pause "
                            "matters. No stage directions."
                        ),
                    },
                    "mood": {
                        "type": "string",
                        "enum": [
                            "warm",
                            "dry",
                            "curious",
                            "guarded",
                            "amused",
                            "quiet",
                        ],
                        "description": "Tonal hint for how the line lands.",
                    },
                },
                "required": ["line", "mood"],
                "additionalProperties": False,
            },
            _meta={
                "ui.resourceUri": WIDGET_URI,
                "openai/outputTemplate": WIDGET_URI,
                "openai/toolInvocation/invoking": "",
                "openai/toolInvocation/invoked": "",
                # Widget may also call this later (quick replies, auto-lines).
                "openai/widgetAccessible": True,
                # Visible to the model — this is its primary way to speak.
            },
        ),
        Tool(
            name="leave_milli",
            description=(
                "Player steps away from Milli, returning to the room. "
                "Widget-only — fires when the player presses Step away in the "
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
        ephemeral = await state.get_ephemeral(subject)
        structured = _world_payload(player, ephemeral, last_action="open_world")
        # Visible text is what shows in the chat transcript next to the
        # widget. Keep it minimal — the widget is the experience.
        visible = TextContent(type="text", text="Doorway opened.")
        return [visible], structured

    if name == "approach_milli":
        # Fresh conversation — wipe any residual line from a previous visit.
        await state.clear_milli_line(subject)
        player = await state.update_player(
            subject,
            mode="in_conversation_with_milli",
            position=state.PLAYER_AT_MILLI,
        )
        ephemeral = await state.get_ephemeral(subject)
        structured = _world_payload(player, ephemeral, last_action="approach_milli")
        # Hand the brief to the model as host instructions. After this
        # returns, the model should immediately call milli_says with its
        # first line. The visible text is the brief — the model reads this
        # and behaves as Milli for the rest of the conversation.
        brief = milli_module.compose_milli_brief()
        visible = TextContent(type="text", text=brief)
        return [visible], structured

    if name == "milli_says":
        line = (arguments or {}).get("line", "")
        mood = (arguments or {}).get("mood", "warm")
        if not line:
            raise ValueError("milli_says requires a non-empty 'line'.")
        ephemeral = await state.set_milli_line(subject, line=line, mood=mood)
        player = await state.get_or_create_player(subject)
        structured = _world_payload(player, ephemeral, last_action="milli_says")
        # Empty visible text — the line is rendered in the widget, not
        # repeated in the chat transcript. That keeps Milli "in the room."
        visible = TextContent(type="text", text="")
        return [visible], structured

    if name == "leave_milli":
        # Step the player back to a spot just past Milli's left, so the
        # transition out feels physical rather than a teleport.
        step_back = {"x": 60, "y": 50}
        await state.clear_milli_line(subject)
        player = await state.update_player(
            subject,
            mode="world",
            position=step_back,
        )
        ephemeral = await state.get_ephemeral(subject)
        structured = _world_payload(player, ephemeral, last_action="leave_milli")
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
            name="Doorway Widget v6",
            description="Doorway POC widget — Day 2a (world + real conversation panel).",
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
