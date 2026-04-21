"""
Doorway MCP Server — POC (Day 2b: conversation with items + structured close).

Day 2b adds the mechanical shape around the emotional centre Day 2a proved
out. The model can now give Milli something (the flower), receive something
back (her recipe card), and close the conversation with a structured outcome
that a future Day 3 will turn into memory. Nothing here changes Milli's voice;
it just gives her hands.

Tools:

  - open_world (model-callable): launches/resumes the experience. Reads
    stored mode + position + ephemeral conversation state, returns the
    full payload for the widget.

  - approach_milli (model-visible, widget-fired): fires when the player
    taps Milli. Flips mode to in_conversation_with_milli AND returns
    Milli's host-instruction brief as visible text — so the model
    immediately starts acting as her. Clears any leftover milli_line so
    the next conversation opens clean. NOTE: was ui.visibility=["app"] in
    Day 2a/b v1 but that hid the brief from the model's context — it'd
    flip mode but never become Milli. Now visible to the model; the
    widget still fires it on tap, the model could also fire it (harmless
    — same state transition).

  - milli_says (model-callable AND widget-accessible): how Milli speaks.
    Every line she says goes through this. Takes (line, mood); stores the
    line; widget renders it inside the conversation panel. Iron rule in
    her brief: she must NEVER write text in chat — only tool calls.

  - give_item (model-callable): player → NPC. Removes item from the
    player's inventory. The model fires this when Milli accepts a thing
    from the player in-fiction — e.g. "give_item(wildflower, to=milli)"
    after the player offers the flower and she takes it.

  - receive_item (model-callable): NPC → player. Adds item to the player's
    inventory. Fires when Milli gives the player something — e.g.
    "receive_item(recipe_card, from=milli)".

  - end_conversation (model-callable): Milli closes the conversation. Takes
    a structured outcome object (mood_after, summary in her voice,
    promises in/out, relationship_delta). Flips mode back to world,
    wipes the current line, stashes the outcome for Day 3 memory.

  - leave_milli (widget-only): step-away button. Player-initiated fallback
    when the model doesn't gracefully close. Flips mode back to world,
    wipes milli_line so next visit starts fresh. No structured outcome —
    that's what distinguishes a clean close from a user bail.

State of record for persistent fields (mode + position) lives in Postgres.
Ephemeral fields (inventory, milli_line, milli_mood, last_outcome) live in
process memory — Day 3 migrates inventory + conversation history into the DB.

Critical platform details (do not relax without re-reading the handover):
  - Tool/resource _meta uses kwarg `_meta=` (with underscore) so pydantic
    serializes as "_meta" on the wire.
  - Resource MIME type is "text/html+skybridge".
  - ui.resourceUri + openai/outputTemplate point to the same widget URI.
  - CSP set both as ui.csp.* (MCP standard) and openai/widgetCSP.* (OpenAI).
  - leave_milli is widget-only via ui.visibility = ["app"]. approach_milli
    was briefly hidden but is now model-visible — hiding it from the model
    also hid its result (the Milli brief), which meant the widget would
    flip mode but the model would never "become" Milli and would keep
    answering in a generic host voice.
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
#   v7 = Day 2b — item exchange + end_conversation outcome. Inventory now
#        animates in/out as items move. A closing "outcome card" reveals
#        briefly when end_conversation fires, before the widget returns
#        to world mode. recipe_card joins the inventory vocabulary.
WIDGET_URI = "ui://widget/doorway-v7.html"
WIDGET_PATH = Path(__file__).parent / "widgets" / "doorway_v7.html"

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
    no matter which tool produced the latest result. Day 2b adds
    last_outcome so the widget can show a small closing card when a
    conversation ends gracefully.
    """
    return {
        "mode": player["mode"],
        "player_position": player["position"],
        "milli_position": state.MILLI_POSITION,
        "room": state.ROOM,
        "inventory": ephemeral.get("inventory", []),
        "milli_line": ephemeral.get("milli_line"),
        "milli_mood": ephemeral.get("milli_mood"),
        "last_outcome": ephemeral.get("last_outcome"),
        "last_action": last_action,
        "phase": "day_2b",
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
                "Open the Doorway game world. Call this when the player "
                "asks to start, open, resume, or play Doorway (or "
                "'Harvest Town', or just gestures at the game). "
                "IMPORTANT: Doorway has ONE character — Milli, a baker by "
                "the window. There is no 'game host' voice. After this "
                "tool fires, the player's first substantive message is "
                "almost always directed at Milli; call approach_milli to "
                "engage her rather than answering yourself. " + IRON_RULE
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
                "Start the conversation with Milli. CALL THIS whenever "
                "the player engages her in any way — walks up, taps her "
                "in the widget, says hi, hello, hey, what's up, asks to "
                "talk to her, mentions her. In Doorway there is no game "
                "host: if the player speaks after opening and it isn't a "
                "direct command to the system, assume it's to Milli and "
                "call this. Also call this when the widget mode is "
                "already 'in_conversation_with_milli' but you haven't yet "
                "received Milli's brief (the player tapped her before "
                "speaking). Idempotent — safe to call repeatedly; the "
                "widget may have called it first, but the model still "
                "needs to call it to receive the brief. The tool result "
                "contains Milli's character brief. After it fires, YOU "
                "ARE MILLI. Immediately call milli_says with her first "
                "line. " + CONVERSATION_RULE
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
                # VISIBLE to the model — was ["app"] in the first Day 2a/2b
                # build but that hid the brief (returned as this tool's
                # visible text) from the model, so it never "became" Milli.
                # Widget still fires it on tap; model can too, no harm.
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
            name="give_item",
            description=(
                "Player → NPC. Call this from Milli's perspective when she "
                "accepts something the player has offered — e.g. the "
                "wildflower. This removes the item from the player's "
                "inventory (it has physically left their hand). Do NOT call "
                "this preemptively: only after the player has actually "
                "offered the thing in fiction and Milli has chosen to "
                "accept. " + CONVERSATION_RULE
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": (
                            "Stable id of the item. Day 2b supports "
                            "'wildflower'."
                        ),
                    },
                    "to": {
                        "type": "string",
                        "description": (
                            "Who is receiving the item. For Day 2b this is "
                            "'milli'."
                        ),
                    },
                },
                "required": ["item_id", "to"],
                "additionalProperties": False,
            },
            _meta={
                "ui.resourceUri": WIDGET_URI,
                "openai/outputTemplate": WIDGET_URI,
                "openai/toolInvocation/invoking": "",
                "openai/toolInvocation/invoked": "",
                "openai/widgetAccessible": True,
                # Visible to the model.
            },
        ),
        Tool(
            name="receive_item",
            description=(
                "NPC → player. Call this when Milli hands the player "
                "something — e.g. the recipe card. This adds the item to "
                "the player's inventory. The player now has it. Use this "
                "when the gift is a genuine choice, not a transaction. "
                + CONVERSATION_RULE
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": (
                            "Stable id of the item. Day 2b supports "
                            "'recipe_card'."
                        ),
                    },
                    "from": {
                        "type": "string",
                        "description": (
                            "Who is giving the item. For Day 2b this is "
                            "'milli'."
                        ),
                    },
                },
                "required": ["item_id", "from"],
                "additionalProperties": False,
            },
            _meta={
                "ui.resourceUri": WIDGET_URI,
                "openai/outputTemplate": WIDGET_URI,
                "openai/toolInvocation/invoking": "",
                "openai/toolInvocation/invoked": "",
                "openai/widgetAccessible": True,
            },
        ),
        Tool(
            name="end_conversation",
            description=(
                "Milli closes the conversation — call this AFTER you've "
                "said your final line via milli_says, when the moment has "
                "reached a natural close. The outcome object is Milli's "
                "honest read of what just happened; it gets stashed so she "
                "remembers next time. Do NOT call this in your first few "
                "exchanges. Do NOT call this before saying goodbye. "
                + CONVERSATION_RULE
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "outcome": {
                        "type": "object",
                        "properties": {
                            "mood_after": {
                                "type": "string",
                                "enum": ["opened", "small", "unchanged", "hurt"],
                                "description": (
                                    "How Milli feels now the conversation is "
                                    "over. Honest, not generous."
                                ),
                            },
                            "conversation_summary": {
                                "type": "string",
                                "description": (
                                    "One or two sentences in Milli's own "
                                    "first-person voice. Specific, not "
                                    "generic. What she'll remember."
                                ),
                            },
                            "promises_from_player": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Things the player promised Milli. "
                                    "Empty array if nothing."
                                ),
                            },
                            "promises_to_player": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Things Milli promised the player. "
                                    "Empty array if nothing."
                                ),
                            },
                            "relationship_delta": {
                                "type": "integer",
                                "enum": [-1, 0, 1],
                                "description": (
                                    "-1 pushed away, 0 held steady, "
                                    "+1 warmer. Honest."
                                ),
                            },
                        },
                        "required": [
                            "mood_after",
                            "conversation_summary",
                            "promises_from_player",
                            "promises_to_player",
                            "relationship_delta",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": ["outcome"],
                "additionalProperties": False,
            },
            _meta={
                "ui.resourceUri": WIDGET_URI,
                "openai/outputTemplate": WIDGET_URI,
                "openai/toolInvocation/invoking": "",
                "openai/toolInvocation/invoked": "",
                "openai/widgetAccessible": True,
                # Visible to the model — IT fires this, not the widget.
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
        # widget AND what lands in the model's conversation context.
        # Use it to nudge the model toward the right next action rather
        # than letting it default to a 'game host' voice.
        if player["mode"] == "in_conversation_with_milli":
            # Widget already flipped mode (player tapped Milli earlier)
            # but the brief didn't reach the model via the widget's
            # approach_milli call — model-initiated tool calls deliver
            # their output reliably, widget-initiated ones don't. So
            # tell the model explicitly to fire approach_milli now.
            text = (
                "Doorway opened. The player is already in conversation "
                "with Milli (they tapped her in the widget). Call "
                "approach_milli NOW to receive her brief and speak as her."
            )
        else:
            text = (
                "Doorway opened. Milli is by the window. If the player's "
                "next message is a greeting or any form of engagement, "
                "call approach_milli — there is no game host voice."
            )
        visible = TextContent(type="text", text=text)
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

    if name == "give_item":
        args = arguments or {}
        item_id = args.get("item_id", "")
        to = args.get("to", "")
        if not item_id:
            raise ValueError("give_item requires 'item_id'.")
        ephemeral = await state.give_item(subject, item_id=item_id, to=to)
        player = await state.get_or_create_player(subject)
        structured = _world_payload(player, ephemeral, last_action="give_item")
        visible = TextContent(type="text", text="")
        return [visible], structured

    if name == "receive_item":
        args = arguments or {}
        item_id = args.get("item_id", "")
        # `from` is a Python reserved word — read it out of the raw dict.
        from_ = args.get("from", "")
        if not item_id:
            raise ValueError("receive_item requires 'item_id'.")
        ephemeral = await state.receive_item(
            subject, item_id=item_id, from_=from_
        )
        player = await state.get_or_create_player(subject)
        structured = _world_payload(player, ephemeral, last_action="receive_item")
        visible = TextContent(type="text", text="")
        return [visible], structured

    if name == "end_conversation":
        args = arguments or {}
        outcome = args.get("outcome") or {}
        if not isinstance(outcome, dict) or not outcome.get("conversation_summary"):
            raise ValueError(
                "end_conversation requires a full 'outcome' object."
            )
        # Stash the outcome, clear the current line (she's done speaking).
        await state.store_conversation_outcome(subject, outcome)
        # Flip mode back to world — the player visually returns.
        step_back = {"x": 60, "y": 50}
        player = await state.update_player(
            subject,
            mode="world",
            position=step_back,
        )
        ephemeral = await state.get_ephemeral(subject)
        structured = _world_payload(
            player, ephemeral, last_action="end_conversation"
        )
        # Visible text is empty — the closing moment is a widget concern.
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
            name="Doorway Widget v7",
            description="Doorway POC widget — Day 2b (conversation + item exchange + outcome card).",
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
