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

## First results

The first raw-block experiment trained a 201k-parameter masked denoiser. It learned broad terrain texture but produced homogeneous bands and needed heavy connectivity repair. Raw native block IDs are therefore not the preferred learning representation.

The first block-level semantic experiment expanded the corpus to 1,324 training windows from 46 route maps across pokered, Star Beasts: Comet, Pokémon Yume, and Pokémon Amaranth. Its 84k-parameter denoiser still produced stripe-like macro structure. The graph baseline remained much stronger on connectivity and visible route composition.

A separate failure was traced to materialization: collision-equivalent native blocks were visually inconsistent. Native style profiles now constrain materialization to coherent block families; Jev will select the style profile rather than individual cells.

The current experiment moves to a 20×36 half-block semantic grid. Each 4×4 native Red block is represented by a 2×2 semantic signature before training, then a deterministic style-aware solver maps four semantic quadrants back to one legal native block. This gives the learned prior enough spatial resolution to model bends, clearings, chokepoints and loops without generating pixels.
