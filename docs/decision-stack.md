# Decision stack: ROM pressure, Jev, and Needle

## Principle

Infinite Red should spend expensive generative intelligence only where it changes the player's experience.

The generation stack is deliberately asymmetric:

1. **deterministic policy** establishes hard constraints and progression pressure;
2. **Jev** makes most high-frequency semantic choices;
3. **Needle 3** runs locally for structured storyline planning and callbacks;
4. deterministic native-data materialization turns the plan into `pokered` data;
5. validators can reject or repair the plan;
6. a frontier model is optional and exceptional.

The fuzzy-calc toolkit supplied during design is a reference for Jev and Needle invocation patterns only. Infinite Red does not vendor or import fuzzy-calc.

## ROM occupancy as progression input

ROM usage is an explicit input to the progression policy:

```text
progress_policy(
    predecessor_challenge,
    organic_target,
    badge_progress,
    unresolved_promises,
    rom_usage_ratio,
)
```

`rom_usage_ratio` is 0..1 and should ultimately come from the native build/materialization pipeline.

The current provisional modes are:

| Effective ROM usage | Mode | Director behavior |
| ---: | --- | --- |
| < 70% | expanding | freely establish new threads and branches |
| 70–88% | converging | prefer callbacks and reduce branch growth |
| 88–97% | endgame | strongly prioritize unresolved promises and high-value milestones |
| >= 97% | finalize | no new promises; one forward path; force finale planning |

These are policy defaults, not cartridge constants. They should be tuned against generated campaigns.

ROM pressure also establishes a rising **difficulty floor**. Organic area-to-area challenge increases still matter, but usable ROM nearing exhaustion can no longer leave the campaign in a low-difficulty state. At finalization pressure, target difficulty reaches the configured maximum.

The Director must not treat 100% as a cliff. The entire 70–100% region is a convergence runway.

## Measuring ROM occupancy

Use **allocatable ROM capacity**, not raw output file size.

RGBDS can emit a linker map with section placement. The native materializer should derive:

- total allocatable bytes;
- currently occupied section bytes;
- usable holes by bank;
- bytes reserved for runtime seam / save compatibility / emergency finale content;
- largest contiguous free regions where relevant.

Then:

```text
rom_usage_ratio =
    1 - usable_unreserved_free_bytes / usable_unreserved_capacity
```

A bank-fragmentation penalty may later be added so many unusably small holes count as less free space.

## Jev: primary decision fabric

Jev is the default model for decisions that can be represented as typed classification, choice, yes/no, or score questions.

It should be called in **batches** so one area-generation request can answer many decision points cheaply.

Examples:

### Macro decisions

- area archetype: route / settlement / dungeon / interior;
- continue exploring vs resolve an existing promise;
- which unresolved promise deserves payoff now;
- connect to a known area vs create a new frontier;
- gate type: HM / item / badge / trainer / NPC / story;
- reward category;
- whether current ROM pressure warrants a major milestone;
- whether this area should begin/advance/finalize an arc.

### Map-composition decisions

- native tileset/template family;
- path topology family;
- landmark category;
- grass/water density bucket;
- trainer-density bucket;
- encounter ecology bucket;
- optional vs mandatory branch;
- native script archetype.

### Repair decisions

When deterministic validation rejects a materialized area, Jev chooses among bounded repair strategies rather than regenerating everything:

- reroute path;
- move object;
- replace block family;
- remove optional branch;
- change gate mechanic;
- reconnect to another known edge;
- simplify story beat.

### Contract

Jev decisions are **advisory semantic choices**. They never bypass deterministic validation and never emit arbitrary assembly.

For reproducibility, production generation should pin a Jev version. `~typesafe/jev-latest` is useful for benchmarking, but saved worlds should record the exact model version used for each generated area.

## Needle 3: local story planner

Needle is not used as a general chat writer.

Its role is to turn current narrative state into **typed story-beat calls** that remain cheap and on-device.

The tool vocabulary in `schemas/needle-story-tools.json` includes operations such as:

- establish a setup;
- advance an existing thread;
- resolve a promise;
- stage a rival beat;
- place a clue or rumor;
- connect an NPC to an existing callback;
- schedule a finale beat.

Needle supplies structured arguments such as involved promise IDs, NPC role, mechanic, callback, reveal function, and dialogue intent.

Red-style dialogue can then be:

1. selected from templates;
2. filled from the structured beat;
3. optionally escalated to a larger model only when genuinely useful.

This keeps local generation coherent without asking a tiny model to be a novelist.

## Suggested per-area call graph

```text
native build stats
      |
      v
progress_policy()  -----> closure mode / difficulty floor / payoff quota
      |
      v
Jev batch ------------------------------------------------------+
  area type                                                     |
  topology                                                      |
  payoff target                                                 |
  gate/reward                                                   |
  encounter/trainer profile                                     |
  map/script archetypes                                         |
      |                                                         |
      +---- if narrative beat required ---> Needle story tools  |
      |                                      |                  |
      v                                      v                  |
validated semantic AreaPlan <-----------------------------------+
      |
      v
native pokered materializer
      |
      v
structural + ROM-space validator
      |
      +---- invalid ---> Jev bounded repair choice ---> retry
      |
      v
pokered build / dynamic-content seam
```

## Escalation policy

A frontier model is not in the normal generation loop.

Escalate only for cases such as:

- Needle cannot express a required multi-thread narrative relationship with adequate confidence;
- a rare story climax needs richer dialogue;
- repeated Jev repair choices fail deterministic validation;
- an unusual reconnection requires broader planning than the typed decision vocabulary captures.

The resulting plan still passes through the same deterministic materializer and validator.
