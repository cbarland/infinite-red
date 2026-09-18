# Infinite Red

Infinite Red is a persistent, effectively infinite Pokémon-style world generated from a small set of validated game primitives. The long-term Director can use an LLM, but the world model, progression rules, and validator do not depend on one.

The repository now contains the first buildable vertical slice:

**Oak's Lab → starter choice → rival milestone → generated origin settlement → persistent frontier expansion.**

Seed `42` deterministically produces a **Mountain Village** at challenge **1.17**, with an open east frontier and a north road blocked by the `STORY:ROAD_CLEARED` promise.

## Repository layout

- `core/world/` — engine-independent Rust world graph, progression, gates, promises, deterministic generator, validator
- `tools/worldgen/` — CLI bridge used by the first Godot vertical
- `runtime/godot/` — Godot 4 presentation/runtime
- `schemas/` — serialized world-state contract
- `docs/architecture.md` — architecture and next milestones

## Build the first vertical

Requirements:

- Rust stable
- Godot **4.7.2** or newer 4.7 stable build

### Windows PowerShell

```powershell
./scripts/build_vertical.ps1
```

Then open `runtime/godot/project.godot` in Godot and run the project.

### Linux / macOS shell

```bash
./scripts/build_vertical.sh
```

Then open `runtime/godot/project.godot` in Godot and run the project.

Controls: **WASD / arrows** move, **E / Enter** interacts, **F5** resets the save to seed 42.

The runtime stores its world at Godot's `user://world.json`, so generated areas persist across restarts.

## CLI smoke test

```bash
cargo build --release -p infinite-red-worldgen
./target/release/worldgen bootstrap --seed 42 --output /tmp/world.json
./target/release/worldgen choose-starter --state /tmp/world.json --starter charmander
./target/release/worldgen defeat-rival --state /tmp/world.json
./target/release/worldgen expand --state /tmp/world.json --area oaks_lab --exit south_door
./target/release/worldgen validate --state /tmp/world.json
```

CI runs the same flow, parses the Godot project headlessly, exports a Linux build, and publishes the playable build as a workflow artifact.

## Asset policy for the scaffold

The first vertical uses placeholder geometry and does not commit a Pokémon ROM or extracted commercial assets. The planned `pokered` reference/import layer remains separate from the world core so we can change asset/runtime strategy without rewriting generation logic.

See [`docs/architecture.md`](docs/architecture.md) for the full design.
