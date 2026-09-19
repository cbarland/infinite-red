# Native data pipeline

## Purpose

Infinite Red should generate **Pokémon Red content**, not a lookalike scene.

This document defines the boundary between the decision system and the original game.

## Upstream source

The adapter targets the pinned `pret/pokered` commit in `config/pokered-source.toml`.

Relevant native sources include:

| Concern | Native source |
| --- | --- |
| map dimensions / IDs | `constants/map_constants.asm` |
| tileset + connections | `data/maps/headers/*.asm` |
| block grid | `maps/*.blk` |
| border / warps / signs / NPCs | `data/maps/objects/*.asm` |
| block → tile expansion | `gfx/blocksets/*.bst` |
| tile graphics | `gfx/tilesets/*.png` / generated `.2bpp` |
| tileset semantics | `data/tilesets/*.asm` |
| encounters | `data/wild/*` |
| scripts | `scripts/*.asm` |
| text | `text/*.asm` |
| sprites | `gfx/sprites/*`, map sprite-set data |
| map music | `data/maps/songs.asm` |

For example, Pallet Town declares:

- `map_header PalletTown, PALLET_TOWN, OVERWORLD`
- north connection to Route 1
- south connection to Route 21

Its object file declares border block `$0b`, three warps, four background events and three object events. Its dimensions are 10 × 9 and `maps/PalletTown.blk` is 90 bytes, so the native block grid is directly inspectable and reproducible.

## Planner output

The Director should output semantic intent, for example:

```text
kind: route
theme: wooded foothills
connect_from: west
connect_to: unresolved east frontier
challenge_delta: small
landmarks:
  - ledge shortcut returning west
  - tall grass pocket
  - trainer overlook
gate_setup:
  mechanic: CUT
  payoff: optional northern spur
```

It should not output pixels or arbitrary collision polygons.

## Materializer output

The deterministic materializer selects legal native primitives and produces:

1. map dimensions
2. tileset
3. block-ID grid
4. map connections
5. border block
6. warps
7. object/background events
8. encounter table
9. scripts/text
10. progression/event references

The result should be buildable by the normal `pokered` toolchain.

## Learning a block vocabulary

We should not hand-author a parallel tile grammar if the decomp already contains the relevant information.

The adapter can derive block semantics from:

- native collision tables
- grass-tile definitions
- warp tile IDs
- ledge/pair-collision data
- water and animation behavior
- frequency and neighborhood context of block IDs in existing maps
- object and warp placements in original maps

This gives the generator a vocabulary such as path, grass, water edge, building frontage, doorway, ledge, fence, tree boundary and so on while preserving the exact native block IDs.

Human-authored semantic overrides are acceptable where inference is ambiguous, but the stored primitive remains the native Red block ID.

## Validation

Every generated map should pass structural checks before compilation:

- dimensions match block byte count
- every block ID exists in the selected blockset
- required entry and exit cells are traversable
- native connections align at their offsets
- every warp destination exists
- every object sits on a valid location
- no required path is accidentally blocked
- gates use mechanics Red already supports whenever possible
- encounter/trainer levels respect the local challenge target
- known-area reconnections preserve graph topology

Then the normal `pokered` build is the final validator.

## ROM budget feedback

The build/materializer must report usable ROM occupancy back to the Director. Prefer linker section placement from the RGBDS map output over raw ROM file length. RGBDS map files enumerate section placement, which lets us account for bank-local free regions and reserve headroom for the dynamic seam and finale content.

The world progression policy accepts `rom_usage_ratio` explicitly. As capacity fills, generation should:

- raise the minimum challenge floor;
- reduce the number of new frontiers;
- stop creating new story promises;
- prioritize resolution of outstanding promises;
- concentrate badges/items/bosses and other milestones;
- enter a forced-finale mode before allocatable space is exhausted.

The policy should retain a nonzero safety reserve so a generated world cannot consume the final bytes needed to close itself coherently.

## Runtime extension policy

Do not patch the engine simply because generation is easier elsewhere.

A framework change is justified only when all three are true:

1. native data cannot express the required behavior,
2. the behavior is essential to open-ended generation, and
3. the patch can be kept behind a narrow compatibility boundary.

The expected unavoidable issue is dynamic availability of newly generated map data. We will address that only after the offline native pipeline is proven.

Candidate seams should be evaluated by code size, number of engine call sites affected, save compatibility, emulator portability and whether ordinary authored maps remain completely unchanged.
