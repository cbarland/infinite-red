# Infinite Red architecture

## Product contract

Infinite Red should feel like Pokémon Red discovering a coherent world beyond the edge of the cartridge.

The governing implementation rule is **data first, engine changes last**. The decompilation is the game. Infinite Red should arrange and generate the same data the original engine already consumes instead of recreating movement, battles, collision, encounters, menus, maps, or rendering in another runtime.

## Design law: native Red data

The Director never draws a map and never talks to a renderer. It proposes game content. A deterministic materializer converts that proposal into native `pokered` structures.

For a generated area, prefer changing only:

- map dimensions and block grid
- map header and map connections
- border block
- warps
- background/sign events
- object/NPC/trainer events
- encounter tables
- trainer parties
- text and scripts
- event flags / progression data
- music / tileset selection

The original engine remains responsible for expanding blocks into tiles, collision, movement, warps, text boxes, battle execution, field moves, menus, audio, saves, and every other behavior it already supports.

If a feature can be expressed as ordinary Red data, it must be expressed as ordinary Red data.

## Layers

### 1. Director — decisions, not implementation

The Director receives compact world state:

- area just left
- badge count
- coarse level/progression hint
- nearby explored topology
- inventory / HM / key-item milestones
- unresolved setups and payoffs
- recent story and encounter history

It proposes semantic content such as:

- route, town, dungeon, interior
- exits and intended connections
- trainers and wild encounter character
- NPC roles
- story setup/payoff
- HM, badge, key-item, battle, or NPC gates
- landmarks and traversal constraints

The Director should not select raw tile pixels. It may choose from known game-native concepts and templates.

### 2. Native data materializer — deterministic

The materializer translates the plan into valid `pokered` data.

For outdoor maps this primarily means selecting and arranging native block IDs from the chosen blockset, then emitting compatible headers, connections, objects, encounters, scripts and text.

It validates:

- all exits are reachable as intended
- connections line up
- warps have valid targets
- required objects fit walkable locations
- gates are realizable by existing engine mechanics
- challenge grows modestly from the preceding area
- existing setup/payoff promises remain coherent
- reconnecting two known areas is topologically consistent

### 3. Pokémon Red runtime

`pret/pokered` is the target runtime and source of truth.

The existing engine should execute generated data without being aware of the Director. Infinite Red should not replace its map renderer, battle engine, object system, encounter system, field moves, menus, save behavior, or scripting system unless a hard requirement cannot be met through data.

### 4. Minimal dynamic-content seam

A truly open-ended world eventually requires one capability the stock cartridge was not designed for: loading newly generated native data after play has begun.

That seam is the exception to the data-first rule. It should be as narrow as possible and live near existing map/data lookup boundaries.

Before modifying the engine, we first prove the entire materialization pipeline offline against unmodified `pokered`. Only after that proof do we choose the smallest runtime extension needed for dynamic loading and persistence.

## Decomp source pin

Development is currently pinned to:

- repository: `pret/pokered`
- upstream commit: `a1a22aaf84d1675bcdbaeb194592379d586d838e`

The pin is recorded in `config/pokered-source.toml`.

## Native-map proof target

The first replacement for the Godot geometry prototype is a byte/data-level round trip of Pallet Town:

1. Read `PALLET_TOWN` dimensions from `constants/map_constants.asm` (10 × 9).
2. Read the 90-byte `maps/PalletTown.blk` grid — one native block ID per map cell.
3. Resolve `OVERWORLD` from `data/maps/headers/PalletTown.asm`.
4. Expand block IDs through `gfx/blocksets/overworld.bst`.
5. Render those tile IDs with `gfx/tilesets/overworld.png`.
6. Parse `data/maps/objects/PalletTown.asm` for border block, warps, signs and objects.
7. Compare the reconstructed result against the known game map.
8. Emit an equivalent native map and build it with the normal `pokered` toolchain.

Once exact round-trip reconstruction works, generation operates at the block/object/script level rather than inventing a separate map representation.

## Existing Godot vertical

The Godot vertical remains useful only as a test harness for the world-decision logic already written. It is **not** the intended game runtime.

No additional gameplay systems should be implemented in Godot unless they are specifically useful for testing the planner/materializer independently of the ROM build.

## Near-term milestones

1. Native Pallet Town parser + renderer.
2. Exact native round-trip test for Pallet Town.
3. Build a modified Pallet Town using only data changes and the stock engine.
4. Define semantic tags for native Overworld blocks from collision/warp/ledge data plus observed use in original maps.
5. Generate a new route/town as a native block grid and compile it into `pokered`.
6. Connect that generated map to an existing map using native connection data.
7. Add native trainers, encounters, signs and scripts.
8. Profile the existing map-loading path and choose the smallest dynamic-content seam.
