# Infinite Red architecture

## Product contract

Infinite Red should feel like Pokémon Red discovering a coherent world beyond the edge of the cartridge rather than a level-scaled randomizer.

The player moves through persistent areas. A newly generated area receives the previous area, badge count, a coarse player-level hint, world history, outstanding setup/payoff promises, and the chosen exit. Progression pressure comes primarily from the previous area's challenge. Player level is contextual input, not the dominant difficulty formula.

## Layers

### 1. World core — Rust, deterministic

The core owns canonical truth:

- graph of areas and bidirectional connections
- player progression milestones
- challenge curve
- generated frontier exits
- gates: HMs, key items, badges, story flags and NPC/battle milestones
- unresolved setups/promises for future payoff
- validation and serialization

This layer must be testable without graphics, a ROM, or an LLM.

### 2. Director — constrained planner

The eventual Director sees a compact world-state summary and proposes an area plan. It may decide to:

- place an HM/key-item/badge/story/NPC gate
- create an obstacle now that pays off later
- resolve an earlier promise
- connect to a previously explored area
- schedule a trainer or story battle
- vary biome, settlement, dungeon and route structure

The Director does **not** directly mutate canonical state. Its proposal passes through deterministic validation/materialization.

The first vertical uses the deterministic fallback planner so CI and offline play require no API key.

### 3. Generator/materializer

The generator turns a validated plan into concrete area primitives. Connections to explored areas must preserve topology and should be coherent from both directions. New challenge increments are deliberately small.

### 4. Runtime — Godot 4

Godot presents the world, gathers interactions and invokes the external `worldgen` bridge. The vertical uses placeholder shapes deliberately; visual asset strategy is separable from world generation.

## First vertical

1. Boot at Oak's Lab.
2. Pick Bulbasaur, Charmander or Squirtle.
3. Trigger a deliberately simplified rival milestone.
4. South door becomes traversable.
5. Generator materializes a persistent Mountain Village.
6. The village contains:
   - back-link to the lab
   - open east frontier
   - north road setup blocked on `STORY:ROAD_CLEARED`
   - guide NPC and optional-trainer primitive
7. State is written to `user://world.json`.
8. Restarting the game reloads the same generated graph.

This proves the critical seam: authored Pokémon-like content can hand off to generation and come back again without the generated world being renderer-owned.

## Near-term milestones

- replace rival milestone with a minimal real turn-based battle core
- add typed species/encounter tables and trainer parties
- materialize generated maps from tile grammar instead of generic rectangles
- add Director proposal schema and LLM adapter
- implement promise resolution and reconnect-to-known-area proposals
- add HM/key-item acquisition and validator tests
- establish legal/user-supplied asset/import path for stronger Pokémon Red presentation
