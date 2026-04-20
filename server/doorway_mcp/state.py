"""
Doorway state layer.

Source of truth for per-player game state. Lives in Postgres in production,
falls back to in-memory dict locally so smoke tests run without a DB.

The fallback matters: Paul's local dev environment doesn't have a Postgres
running, but he still needs `./smoke_test.sh` to work end-to-end. When
DATABASE_URL is unset, we just keep state in process memory — fine for
local iteration, useless across restarts, but it's not meant to be durable
locally.

Per the hybrid pattern from CHATGPT_APP_HANDOVER.md:
  - State of record lives here, keyed on openai/subject (or 'anonymous' if
    the host doesn't supply a subject).
  - Tools call into this module on every state-changing action.
  - The widget never holds load-bearing state in JS — it renders from
    structuredContent every mount.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

# ---------------------------------------------------------------------------
# In-memory fallback (used when DATABASE_URL is unset)
# ---------------------------------------------------------------------------

_memory_store: dict[str, dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Postgres pool (lazy)
# ---------------------------------------------------------------------------

_pool = None  # asyncpg.Pool | None


async def _get_pool():
    """Return an asyncpg pool, or None if no DATABASE_URL is set."""
    global _pool
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    if _pool is None:
        # Import lazily so the server still starts even if asyncpg has trouble
        # in some weird environment.
        import asyncpg

        _pool = await asyncpg.create_pool(db_url, min_size=1, max_size=4)
    return _pool


# ---------------------------------------------------------------------------
# World layout — Day 1 keeps this static
# ---------------------------------------------------------------------------

# Coordinates are abstract 0–100 percentages; the widget maps them to pixels
# based on the actual room canvas size. This keeps server math simple and
# decouples gameplay coordinates from screen size.
ROOM = {
    "width": 100,
    "height": 100,
    # Static furniture for the widget to render. Server doesn't enforce
    # collision — Day 1 is a single open room.
    "furniture": [
        {"id": "window",   "x": 70, "y": 18, "w": 22, "h": 12, "kind": "window"},
        {"id": "counter",  "x": 60, "y": 30, "w": 35, "h": 8,  "kind": "counter"},
        {"id": "table",    "x": 30, "y": 55, "w": 18, "h": 14, "kind": "table"},
        {"id": "door",     "x": 8,  "y": 72, "w": 4,  "h": 16, "kind": "door"},
    ],
}

# Milli stands by the window. Static for Day 1; she gets a schedule later.
MILLI_POSITION = {"x": 78, "y": 32}

# When the player approaches Milli, they end up at this spot (just to her left).
PLAYER_AT_MILLI = {"x": 70, "y": 36}

# Player's default starting position — by the door, lower-left.
DEFAULT_PLAYER_POSITION = {"x": 18, "y": 80}


# ---------------------------------------------------------------------------
# Subject helpers
# ---------------------------------------------------------------------------

def resolve_subject(subject_id: Optional[str]) -> str:
    """ChatGPT usually sends openai/subject, but in some dev-mode flows it
    doesn't. Fall back so the server still works rather than crashing."""
    return subject_id or "anonymous"


def _default_state() -> dict:
    return {
        "mode": "world",
        "position": dict(DEFAULT_PLAYER_POSITION),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_or_create_player(subject_id: Optional[str]) -> dict:
    """Return current player state. Creates a default row if missing."""
    sid = resolve_subject(subject_id)
    pool = await _get_pool()

    if pool is None:
        if sid not in _memory_store:
            _memory_store[sid] = _default_state()
        # Return a copy so callers can't accidentally mutate the store.
        return _deep_copy(_memory_store[sid])

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT mode, position FROM players WHERE subject_id = $1",
            sid,
        )
        if row is None:
            default = _default_state()
            await conn.execute(
                """
                INSERT INTO players (subject_id, mode, position)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (subject_id) DO NOTHING
                """,
                sid,
                default["mode"],
                json.dumps(default["position"]),
            )
            return default
        return {
            "mode": row["mode"],
            "position": _coerce_jsonb(row["position"]),
        }


async def update_player(
    subject_id: Optional[str],
    *,
    mode: Optional[str] = None,
    position: Optional[dict] = None,
) -> dict:
    """Update mode / position; returns the new full state."""
    sid = resolve_subject(subject_id)
    current = await get_or_create_player(sid)

    if mode is not None:
        current["mode"] = mode
    if position is not None:
        current["position"] = position

    pool = await _get_pool()
    if pool is None:
        _memory_store[sid] = _deep_copy(current)
        return _deep_copy(current)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE players
               SET mode = $2,
                   position = $3::jsonb,
                   updated_at = NOW()
             WHERE subject_id = $1
            """,
            sid,
            current["mode"],
            json.dumps(current["position"]),
        )
    return current


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_jsonb(value: Any) -> dict:
    """asyncpg may return JSONB as either dict or str depending on version."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


def _deep_copy(state: dict) -> dict:
    # Cheap deep copy — state shape is small and JSON-friendly.
    return json.loads(json.dumps(state))
