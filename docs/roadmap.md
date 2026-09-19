# Roadmap

## World anchor

**Pallet Town is the only authored geographic constant.**

Original Kanto map IDs may be reused internally as compatibility slots, but their original names, layouts, encounters, NPC populations, and story identities are not world canon. Slot IDs such as `ROUTE_1` and `VIRIDIAN_CITY` are implementation handles only.

Every location beyond Pallet Town should receive a generated persistent world identity, including its player-facing name.

## First playable vertical — current priority

The shortest path to the actual product is:

1. **Native Pallet Town round-trip**
   - parse native map constants, header, object events and block grid;
   - expand `.blk` through the native blockset;
   - render through the native tileset;
   - emit byte-identical native data.

2. **Generated first route**
   - use the `ROUTE_1` slot only as a compatibility container;
   - preserve only the physical seam into Pallet Town;
   - generate the remaining topology from native Overworld blocks;
   - generate its player-facing name and the identity of its next settlement;
   - generate/reposition signs and NPCs without leaking Kanto slot names;
   - validate connectivity and stock-engine buildability.

3. **Expanded working ROM**
   - build/patch a private working copy;
   - place generated native data in added ROM capacity;
   - keep the user's source ROM untouched.

4. **Phone player**
   - Android shell around an existing accurate Game Boy core;
   - import and verify user-supplied Pokémon Red ROM;
   - create private Infinite Red working cartridge;
   - boot directly into normal Pokémon Red gameplay.

5. **Dynamic frontier seam**
   - add the smallest possible game/emulator handshake for future native areas;
   - pre-generate likely exits;
   - page generated map slots from app-managed world storage.

## Deferred: region transitions

Region transitions are a promising **late-game/postgame extension**. A campaign that reaches its Kanto finale could unlock a transition into another region vocabulary, tileset/ecology/story regime and reset some expansion pressure.

Do not design or implement this until the first vertical above is playable on a phone. The current architecture should merely avoid making region transitions impossible later.
