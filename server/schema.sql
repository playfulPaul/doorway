-- Doorway Postgres schema
--
-- Not used in Day 0. Referenced from Day 1 onwards when real state lands.
-- Apply this in Railway: your Postgres service → Query tab → paste → run.
--
-- Design notes (from DOORWAY_POC_PLAN.md's future-proofing section):
-- 1. Character constants are separated from dynamic state so that adding
--    NPCs later is just inserting more rows of each.
-- 2. Items in give/receive carry a "to" / "from" so 3-way conversations
--    don't require a schema change.
-- 3. Every memory entry carries a provenance tag so a future gossip system
--    can propagate facts between NPCs with attribution.

-- Players — one row per ChatGPT user, keyed on openai/subject.
CREATE TABLE IF NOT EXISTS players (
    subject_id      TEXT PRIMARY KEY,
    inventory       JSONB NOT NULL DEFAULT '[]'::jsonb,
    position        JSONB NOT NULL DEFAULT '{"x": 5, "y": 5}'::jsonb,
    mode            TEXT NOT NULL DEFAULT 'world',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- NPC character constants — voice, history, core identity. Rarely changes.
-- Edited by designers, not by the game loop.
CREATE TABLE IF NOT EXISTS npc_character_constants (
    npc_id          TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    brief_core      TEXT NOT NULL,
    voice_rules     TEXT NOT NULL,
    sample_dialogue JSONB NOT NULL DEFAULT '[]'::jsonb
);

-- NPC dynamic state — per player, changes per conversation.
-- Mood, relationship, what they currently carry, when they last saw the player.
CREATE TABLE IF NOT EXISTS npc_dynamic_state (
    subject_id      TEXT NOT NULL,
    npc_id          TEXT NOT NULL,
    mood            TEXT NOT NULL DEFAULT 'neutral',
    relationship    INTEGER NOT NULL DEFAULT 0,
    inventory       JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_seen_at    TIMESTAMPTZ,
    PRIMARY KEY (subject_id, npc_id),
    FOREIGN KEY (subject_id) REFERENCES players(subject_id) ON DELETE CASCADE
);

-- NPC memories — a log of past conversations, first-person from the NPC's POV.
-- `provenance` tags how this memory was formed — ready for a gossip system later.
CREATE TABLE IF NOT EXISTS npc_memories (
    id                    SERIAL PRIMARY KEY,
    subject_id            TEXT NOT NULL,
    npc_id                TEXT NOT NULL,
    summary               TEXT NOT NULL,
    mood_after            TEXT,
    promises_from_player  JSONB NOT NULL DEFAULT '[]'::jsonb,
    promises_to_player    JSONB NOT NULL DEFAULT '[]'::jsonb,
    provenance            TEXT NOT NULL DEFAULT 'from_player',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memories_subject_npc
    ON npc_memories (subject_id, npc_id, created_at DESC);

-- Seed Milli's character constants (placeholder — fleshed out on Day 2).
INSERT INTO npc_character_constants (npc_id, name, brief_core, voice_rules, sample_dialogue)
VALUES (
    'milli',
    'Milli',
    'PLACEHOLDER — core brief for Milli lands on Day 2. See DOORWAY_POC_PLAN.md.',
    'PLACEHOLDER — voice rules land on Day 2.',
    '[]'::jsonb
)
ON CONFLICT (npc_id) DO NOTHING;
