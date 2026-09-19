# Route generator bake-off

This experiment compares three ways to generate the first post-Pallet route while staying in Pokémon Red's native Overworld block vocabulary.

1. **Graph grammar** — explicit landmarks, fork/rejoin structure, obstacle islands and a guaranteed macro route.
2. **WFC-style adjacency collapse** — learns native block-neighbor constraints from original Kanto routes.
3. **Tiny masked categorical denoiser** — a very small convolutional masked-diffusion-style model trained directly on native route block grids.

The original Kanto routes are training data only. Generated candidates are scored against the corpus for nearest-source similarity and 2×2 pattern novelty, then pass through the same deterministic connectivity repair and native renderer.

## Fair constraints

Every candidate gets the same 10×18 native block canvas, exact Pallet-facing south seam, seeded north exit, connectivity validator/repair, and Overworld renderer.

## Tiny model

The default denoiser uses 48 channels and four residual convolutional blocks, well under one million parameters. It predicts only native block IDs observed in the route corpus. No pixels are generated.

Training randomly masks 12–100% of cells and learns to reconstruct the native block grid. Sampling starts masked except for hard connection constraints and iteratively commits high-confidence cells.

## Output

The workflow emits per-generator contact sheets, per-seed native Red renders, results.json, report.md, corpus metadata, and tiny-model metadata/checkpoint.

The model checkpoint is experimental and is not part of the production runtime yet.
