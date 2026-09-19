# Generator bake-off

Birch Pass demonstrated that a hand-authored centerline grammar can satisfy native Red constraints while still producing boring composition. The next experiment compares three layout priors under identical constraints.

## Contestants

- graph grammar with explicit fork/rejoin structure and obstacle islands;
- WFC-style native block adjacency collapse;
- tiny masked categorical denoiser over native Overworld block IDs.

## Acceptance criteria

The model is not selected by one scalar score. We care about:

- obvious visual variety across seeds;
- low similarity to the closest original Kanto crop;
- native 2×2 pattern novelty without visual nonsense;
- successful Pallet-to-north traversal;
- little deterministic repair;
- enough terrain/obstacle region structure to create landmarks and choices;
- small model size and phone-plausible inference cost.

All three generators use the same deterministic repair/materialization boundary. The winning prior still does not get authority over Red's engine rules.
