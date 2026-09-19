# Native pokered adapter

This directory is the beginning of the production content path for Infinite Red.

It reads a **separate checkout** of the pinned `pret/pokered` source and works directly with the game's native structures:

- `constants/map_constants.asm`
- `data/maps/headers/*.asm`
- `data/maps/objects/*.asm`
- `maps/*.blk`
- `gfx/blocksets/*.bst`
- `gfx/tilesets/*.png`

No pokered assets are copied into Infinite Red.

## Pallet Town proof

```bash
python -m pip install -r tools/native/requirements.txt
python tools/native/pokered_native.py verify-pallet \
  --repo /path/to/pokered \
  --output out/pallet \
  --scale 2
```

The command asserts the known native contract, expands the native block grid through the native Overworld blockset, renders it with the native tileset, and emits the original `.blk` byte-for-byte plus a parsed manifest.

That is the gate for the next step: produce a generated Route 1 replacement in exactly the same native representation.

## Generated Route 1 proof

```bash
python tools/native/pokered_native.py generate-route1 \
  --repo /path/to/pokered \
  --output out/route1 \
  --seed 42 \
  --scale 2
```

The current first-pass generator is intentionally conservative. It substitutes only native Route 1 blocks with the same 4×4 walkability mask and the same grass positions, never substitutes warp/ledge-special blocks, and keeps all map boundaries unchanged. Seed 42 currently changes 60 of the 180 native block cells.

CI then copies the generated `maps/Route1.blk` into the pinned decomp and builds `pokered.gbc` with the stock engine and RGBDS 1.0.3. The resulting ROM is used only as an ephemeral validation product and is not uploaded as an artifact.
