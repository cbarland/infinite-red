# Infinite Red

Infinite Red is an open-ended Pokémon Red world directed by a constrained decision system and materialized as **native Pokémon Red game data**.

## Core rule

**Arrange the game; do not rebuild the game.**

The target runtime is `pret/pokered`. Generated areas should use the original map block grids, blocksets, tilesets, map headers, connections, objects, encounters, trainers, scripts and text so the existing engine continues to own rendering, collision, movement, battles, menus, field moves and saves.

The earlier Godot vertical remains in the repository as a planner/world-state prototype, but it is no longer the intended production runtime.

## Current architecture

- `core/world/` — deterministic world/progression decision state
- `tools/worldgen/` — current planner/world-state CLI
- `config/pokered-source.toml` — pinned `pret/pokered` revision
- `docs/native-data-pipeline.md` — native Red materialization contract
- `runtime/godot/` — prototype harness only

The next proof is **Pallet Town round trip**: reconstruct it directly from the decomp's 10×9 block grid, Overworld blockset/tileset, header, connections and object data, then emit/build an equivalent native map through the normal `pokered` toolchain.

Only after native offline generation is proven will we modify the game framework at all. The eventual dynamic-content loader should be the smallest possible seam around existing data lookup, while generated content itself remains ordinary Red data.

See `docs/architecture.md` and `docs/native-data-pipeline.md`.
