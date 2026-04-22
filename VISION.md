# Harvest Town — Design Vision

*A living doc. Grows over time. Notes where we've landed and where we're reaching. Not a spec — a feeling to keep checking work against.*

---

## The feeling

Idyllic but not saccharine. Calm and beautiful — being there is the point. But not every character is happy. Some are grumpy, some are wise, some are ditsy, some are formal, some are chaotic, some are quiet. The town is warmer for holding all of them. The player comes to feel they live there — not as a visitor, not as the protagonist, just as someone who belongs on the edge of everyone else's lives.

The AI magic is what makes the emotional beats land. Characters respond as themselves, remember you specifically, react to what just happened rather than to what a writer pre-wrote. But the AI is never the *subject*. It's the thing that lets the village feel like a village.

---

## The townsfolk

A cast of characters with distinct voices, wants, histories, and relationships *with each other*. Milli is the first — dry, warm, grounded, guarded. The roster fills out with range: the point is contrast, not completeness. No two characters should sound the same; none of them should sound like a "villager."

Characters have relationships with each other that evolve independently of the player. Two shopkeepers who bicker. Siblings who don't speak. An old friendship cooling. A new crush. These progress whether the player is looking or not — the world has its own life.

Romantic storylines are available, but this is **not a dating game**. Courtship is one thing a person does; it's not the game's organising principle. The player can pursue a romantic arc with some characters; most characters are just friends, rivals, neighbours. When romance happens, it should feel continuous with everything else — earned attention, small gestures, the particular care of being seen — not a separate minigame.

---

## How they live

Characters have schedules. They wake, work, eat, visit, sleep. They attend events. They come in out of the rain. The schedule is what makes the world feel like it's running whether you're looking or not.

Characters can move. They can be *somewhere* rather than fixed in place. They show up at the square for the festival, at the dock for the fishing competition, at the temple for the full moon. The player learns where to find people and when.

Players and characters can arrange to meet. "Come by the bakery at six." "I'll be at the dock tomorrow morning." When the time comes, they show up — or they have a real excuse, and the excuse matters. **This is delicate.** An AI-generated excuse has to feel real, not procedural. "Sorry, I was busy" is death; "The loaf burned and I had to start over, and then Peder came in asking about the honey delivery, and the afternoon just went" is alive. Excuse design is its own craft — half the feeling of a character living a life is how they fail you.

---

## How they know each other

Information moves through the town naturally. Characters don't need full on-screen conversations — they pass key facts, gossip, rumours to each other. If you tell Milli something, her brother may know it by tomorrow. If you miss a meeting, the innkeeper hears about it.

This is the secret engine of the world feeling alive. Not because every piece of gossip is important — most of it isn't — but because the town has a *nervous system* the player is embedded in rather than floating above.

---

## The world itself

Classic collection systems live here — fishing, foraging, farming. The player engages with the land. The village engages back: Milli wants mushrooms, the brewer needs wild honey, the innkeeper is running out of trout. Classic RPG tropes — cleared paths, gathered ingredients, delivered messages — fold in naturally through characters expressing real wants, not quest exclamation marks.

The town has history. Slightly fractured — no single character knows all of it. Secrets are held and sometimes uncovered. There are things beneath things: a locked chest behind a story, a letter in a loose floorboard, a song no one will sing anymore. Treasure exists and matters, but it is never the point — the point is the story that surrounds it.

---

## The player's place in it

The player is the farmer. That role matters — the town eats what you grow, and being a provider is part of what makes the player belong. But reliance is held lightly. People were fine before you arrived. They're a little better with you here. That asymmetry — they're glad you came, but they'd survive if you left — is what makes the belonging feel earned rather than owed.

The player's day is not an objective queue. It's a day.

---

## What else — Claude's additions

Threads that might help it sing:

**Weather and seasons that bite.** Not decorative rain — rain that floods the bridge. A storm that takes down someone's fence. A drought that makes the brewer grumpy. Weather is the cheapest, strongest way to make the world feel like it has a pulse you don't control.

**Micro-rituals.** The baker opens at six. The temple bell at sunset. The fisherman checks his nets before dawn. These aren't events — they're the texture of place. Once the player knows them without thinking, they feel at home.

**Objects with history.** A necklace that belonged to someone's mother. The well the town was built around. The AI is especially potent on old things — the model can describe the *feeling* of a worn object better than most hand-written dialogue can.

**Unfinished business.** A letter never sent. An old grudge. A song half-written. These are invitations, not quests. They're the player's opportunity to become part of the town's story rather than an outsider solving its puzzles.

**A numinous presence.** A fox that keeps appearing. A well spirit. The old lighthouse. Something not fully explained. Life-sims without a thread of mystery go flat; even a single unresolved shimmer keeps the world feeling deeper than it is.

**Humour.** At least one genuinely funny character. A running joke. Someone with a ridiculous passion. Without comedy, "idyllic" drifts toward saccharine. Comedy is also how warmth travels between players and characters who aren't emotionally close — teasing is easier than tenderness.

**Asymmetric information.** The player knows things characters don't; characters know things the player doesn't. Gossip *needs* this to work. It's also the engine of secrets, surprises, and the feeling that the town is bigger than what you can see at any one time.

**The player has a past, lightly.** Not a full backstory. But hints. Why did they come here? Are they running from something? Were they called? This gives characters something to be curious about, and keeps the player from being a blank avatar.

**Failure that is real but recoverable.** You can hurt someone's feelings; it matters; it doesn't last forever. The possibility of loss is what makes warmth valuable. Some life-sims soften this too much — relationships can only go up — and the love meters become homework.

**Named places and times.** The Whistling Tree. Seven Bridges Creek. The Lantern Month. A few proper nouns for landmarks and seasons is remarkably cheap magic.

---

## What we are not making

Keep this list honest — it's how scope stays inside the walls:

- Not a dating game. Romance is *a* thread, not *the* thread.
- Not a combat game. No enemies, no HP, no weapons-as-stats.
- Not an optimisation game. No XP bars, no crafting tech trees to min-max.
- Not a shop sim. Characters who trade with you do it because they know you, not because of prices.
- Not an open-world RPG. The town is small and deep, not vast.

The design pressure is always: **deeper over wider**.

---

## Where we are now

Milli POC, inside a ChatGPT App called Doorway.

**Day 2b shipped** (2026-04-22): Milli can accept a flower, give a recipe card back, and close the conversation with a structured outcome summarising what happened. Brief is now guardrailed against faking shared history.

**Day 3a — next:** persistent memory log. Milli remembers you between visits. This is the hinge on which everything else swings.

**Day 3b — after that:** Milli gets a *today* (what she's making, what she's short on) and a rule about how needs surface in conversation. First seed of the "characters have specific wants" system that, scaled up, is how classic RPG quests fold invisibly into everyday life.

**Further out:** schedules, second character, intra-character gossip, world traversal, calendar of town events, weather, the first numinous thread.
