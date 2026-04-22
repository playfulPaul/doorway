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

# Ephemeral per-subject state — lives only in process memory, never in
# Postgres. Day 2a/2b use this for the things that are conversation-scoped or
# don't yet need to survive server restarts: current inventory, Milli's last
# spoken line/mood, and the most recent conversation outcome.
#
# Day 2b added:
#   - inventory mutations (give/receive)
#   - last_outcome: the most recent close — used ONLY to render the widget's
#     closing "outcome card" immediately after end_conversation fires. This
#     is not Milli's memory; the durable memory (what she actually reads
#     next time) lives in _outcome_log / the conversation_outcomes table.
_ephemeral_store: dict[str, dict[str, Any]] = {}

# Day 3a — persistent conversation log, in-memory fallback. Key is
# f"{subject_id}:{character_id}"; value is a list of outcome dicts, NEWEST
# FIRST. In production this lives in the conversation_outcomes Postgres
# table; locally it's in-process so smoke tests exercise the full
# read/write path. Unlike _ephemeral_store, this is what Milli pulls from
# when the player returns — the difference between a widget overlay and
# real memory.
_outcome_log: dict[str, list[dict[str, Any]]] = {}


def _log_key(sid: str, character_id: str) -> str:
    return f"{sid}:{character_id}"


def _ephemeral(sid: str) -> dict[str, Any]:
    if sid not in _ephemeral_store:
        _ephemeral_store[sid] = {
            "inventory": ["wildflower"],
            "milli_line": None,
            "milli_mood": None,
            "last_outcome": None,
        }
    return _ephemeral_store[sid]

# ---------------------------------------------------------------------------
# Postgres pool (lazy)
# ---------------------------------------------------------------------------

_pool = None  # asyncpg.Pool | None
_schema_ensured = False


async def _ensure_schema(conn) -> None:
    """Create the conversation_outcomes table if missing. Idempotent — safe
    to call on every pool init. Keeps the schema colocated with the code
    that depends on it so Day 3a deploys don't need a separate migration
    step. `players` table is assumed to already exist from Day 1."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_outcomes (
            id          BIGSERIAL PRIMARY KEY,
            subject_id   TEXT        NOT NULL,
            character_id TEXT        NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            outcome      JSONB       NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conv_outcomes_subject_char_time
            ON conversation_outcomes (subject_id, character_id, created_at DESC)
        """
    )


async def _get_pool():
    """Return an asyncpg pool, or None if no DATABASE_URL is set."""
    global _pool, _schema_ensured
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    if _pool is None:
        # Import lazily so the server still starts even if asyncpg has trouble
        # in some weird environment.
        import asyncpg

        _pool = await asyncpg.create_pool(db_url, min_size=1, max_size=4)
    if not _schema_ensured:
        async with _pool.acquire() as conn:
            await _ensure_schema(conn)
        _schema_ensured = True
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


async def get_ephemeral(subject_id: Optional[str]) -> dict:
    """Return the ephemeral (non-persistent) state for a subject: inventory,
    Milli's latest line/mood. Lives only in process memory."""
    sid = resolve_subject(subject_id)
    return _deep_copy(_ephemeral(sid))


async def set_milli_line(
    subject_id: Optional[str], line: str, mood: str
) -> dict:
    """Record Milli's latest spoken line. Returns the updated ephemeral state."""
    sid = resolve_subject(subject_id)
    eph = _ephemeral(sid)
    eph["milli_line"] = line
    eph["milli_mood"] = mood
    return _deep_copy(eph)


async def clear_milli_line(subject_id: Optional[str]) -> dict:
    """Wipe Milli's current line — called on leave_milli so the next
    conversation opens clean."""
    sid = resolve_subject(subject_id)
    eph = _ephemeral(sid)
    eph["milli_line"] = None
    eph["milli_mood"] = None
    return _deep_copy(eph)


# ---------------------------------------------------------------------------
# Inventory — Day 2b adds the actual push/pull of items between player + NPC
# ---------------------------------------------------------------------------

async def give_item(
    subject_id: Optional[str], item_id: str, to: str
) -> dict:
    """Player gives an item. For Day 2b the only NPC is Milli, so `to` is
    informational — what matters is that the item leaves the player's
    inventory. Idempotent: if the item isn't there, this is a no-op rather
    than an error (the model may fire this more than once).

    Returns the updated ephemeral state so the caller can read back
    inventory + whatever else."""
    sid = resolve_subject(subject_id)
    eph = _ephemeral(sid)
    inv = eph.get("inventory") or []
    if item_id in inv:
        inv.remove(item_id)
    eph["inventory"] = inv
    return _deep_copy(eph)


async def receive_item(
    subject_id: Optional[str], item_id: str, from_: str
) -> dict:
    """Player receives an item. `from_` is informational. Idempotent: if
    the item is already in the inventory, leaves it there rather than
    double-adding."""
    sid = resolve_subject(subject_id)
    eph = _ephemeral(sid)
    inv = eph.get("inventory") or []
    if item_id not in inv:
        inv.append(item_id)
    eph["inventory"] = inv
    return _deep_copy(eph)


async def store_conversation_outcome(
    subject_id: Optional[str], outcome: dict
) -> dict:
    """Stash the end_conversation outcome for the widget's closing card only.
    This is the ephemeral, single-slot version — it is what the widget reads
    to render the small "outcome" overlay right after a conversation ends,
    then the player walks away. Clears milli_line at the same time (the
    conversation is over; she's no longer mid-speech).

    Durable memory — what Milli pulls from on the NEXT visit — lives
    separately in `log_conversation_outcome` / the conversation_outcomes
    table. Day 3a splits these concerns: the widget card and the memory
    log come from the same outcome object but have different lifetimes."""
    sid = resolve_subject(subject_id)
    eph = _ephemeral(sid)
    eph["last_outcome"] = outcome
    eph["milli_line"] = None
    eph["milli_mood"] = None
    return _deep_copy(eph)


# ---------------------------------------------------------------------------
# Day 3a — persistent conversation log (Milli remembers across sessions)
# ---------------------------------------------------------------------------

async def log_conversation_outcome(
    subject_id: Optional[str],
    character_id: str,
    outcome: dict,
) -> None:
    """Append a conversation outcome to the persistent log for
    (subject_id, character_id). This is the memory Milli (or any future NPC)
    reads from on the next encounter.

    Separate from `store_conversation_outcome` on purpose:
      - store_conversation_outcome = the widget's closing card (one slot,
        ephemeral, wiped on next visit).
      - log_conversation_outcome = durable memory (appended, read on
        return). Keyed on character_id so each NPC has their own log with
        this player.

    No-op on empty/malformed outcome — Day 3a leaves the caller to validate
    shape; we just take what we're given."""
    if not isinstance(outcome, dict) or not outcome:
        return
    sid = resolve_subject(subject_id)
    pool = await _get_pool()

    if pool is None:
        key = _log_key(sid, character_id)
        log = _outcome_log.setdefault(key, [])
        # Newest first — matches the SQL ORDER BY shape so local + prod
        # return outcomes in the same order.
        log.insert(0, _deep_copy(outcome))
        return

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversation_outcomes
                (subject_id, character_id, outcome)
            VALUES ($1, $2, $3::jsonb)
            """,
            sid,
            character_id,
            json.dumps(outcome),
        )


async def get_recent_outcomes(
    subject_id: Optional[str],
    character_id: str,
    limit: int = 3,
) -> list[dict]:
    """Return up to `limit` most-recent outcomes for (subject, character),
    newest first. Empty list if none.

    Default limit of 3 keeps the brief bounded — three entries feels like
    real memory (last time + before that + earlier still) without bloating
    the model's context on every approach. Can be tuned per-character later
    if it turns out some NPCs want longer memory than others."""
    sid = resolve_subject(subject_id)
    pool = await _get_pool()

    if pool is None:
        key = _log_key(sid, character_id)
        log = _outcome_log.get(key, [])
        return [_deep_copy(entry) for entry in log[:limit]]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT outcome
              FROM conversation_outcomes
             WHERE subject_id = $1 AND character_id = $2
             ORDER BY created_at DESC
             LIMIT $3
            """,
            sid,
            character_id,
            limit,
        )
        return [_coerce_jsonb(row["outcome"]) for row in rows]


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
