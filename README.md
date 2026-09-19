# Infinite Red

Infinite Red is an open-ended Pokémon Red world directed by a constrained decision system and materialized as **native Pokémon Red game data**.

## Core rule

**Arrange the game; do not rebuild the game.**

The target runtime is `pret/pokered`. Generated areas should use the original map block grids, blocksets, tilesets, map headers, connections, objects, encounters, trainers, scripts and text so the existing engine continues to own rendering, collision, movement, battles, menus, field moves and saves.

The earlier Godot vertical remains in the repository as a planner/world-state prototype, but it is no longer the intended production runtime.

## Current architecture

- `core/world/` — deterministic world/progression decision state
- `tools/worldgen/` — deterministic world/progression state and ROM-pressure policy
- `tools/director/` — thin external Jev and Needle adapters
- `config/pokered-source.toml` — pinned `pret/pokered` revision
- `config/models.toml` — external model roles; no model assets are vendored
- `docs/native-data-pipeline.md` — native Red materialization contract
- `docs/decision-stack.md` — ROM-pressure + Jev + Needle generation policy
- `runtime/godot/` — prototype harness only

The native-data proof is now working: Pallet Town round-trips byte-for-byte from the pinned decomp, and a deterministic Route 1 variant can be generated from native Overworld blocks while preserving its exact collision/grass topology. CI drops that generated `.blk` into an otherwise stock `pret/pokered` checkout and requires RGBDS 1.0.3 to build Pokémon Red successfully.

Only after native offline generation is proven will we modify the game framework at all. The eventual dynamic-content loader should be the smallest possible seam around existing data lookup, while generated content itself remains ordinary Red data.

ROM occupancy is now an explicit progression input. As allocatable ROM space fills, the Director should converge: raise the difficulty floor, stop opening new story threads, resolve outstanding promises, narrow branching, and force a coherent finale before capacity is exhausted. Jev is the intended high-frequency structured decision layer; Needle 3 is the optional on-device structured story planner.

See `docs/architecture.md`, `docs/native-data-pipeline.md`, and `docs/roadmap.md`.
