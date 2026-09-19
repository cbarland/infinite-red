# Route generator bake-off results

## Decision

For the first playable vertical, use:

**graph topology generator -> deterministic validation -> Jev critic/reranker -> Jev style profile -> native Red materializer**

Tiny diffusion remains an experimental **terrain-infill / variation** technique. It is not currently strong enough to own route macro-topology.

## Corpora

The expanded research corpus contains 1,324 route windows from 46 authored route maps:

- pret/pokered: 164 windows
- Star Beasts: Comet: 784 windows
- Pokémon Yume: 212 windows
- Pokémon Amaranth: 164 windows

Third-party repositories are pinned external research sources. Their ROMs/assets are not vendored, and checkpoints trained on them remain research-only pending provenance/licensing review.

## Experiments

### Raw native-block diffusion

The first masked denoiser learned broad texture but tended toward homogeneous bands and required substantial connectivity repair. Native block IDs were too entangled with local visual style to be a good cross-source learning representation.

### Block-level semantic generation

Maps were normalized to four semantic classes: solid terrain, mixed edge, open ground, and grass.

Across eight seeds:

- graph: 100% native connectivity, zero semantic/native repairs, nearest-source similarity 0.490
- WFC: 62% native connectivity, 8.5 semantic repairs/map
- diffusion: 88% native connectivity after repair, 14.88 semantic repairs/map, nearest-source similarity 0.839

The 84,612-parameter diffuser remained visibly stripe-like.

### Half-block semantic generation

Each native 4x4-tile block was expanded to a 2x2 semantic signature, producing a 20x36 topology canvas. A 21,860-parameter dilated convolutional masked denoiser trained in about 19 seconds on CI CPU.

Before the final hard-connectivity fallback:

- graph: 88% native connectivity, zero semantic repairs, nearest-source similarity 0.493
- WFC: 62% native connectivity, 16.12 semantic repairs and 14.88 native repairs/map
- diffusion: 88% native connectivity, 24.5 semantic repairs and 12.25 native repairs/map, nearest-source similarity 0.822

Visually, the half-block graph generator produced the best route-like macro composition: bends, grass fields, clearings, branches and obstacle regions. The diffuser still overproduced large homogeneous terrain masses.

A final tile-level native connectivity fallback now guarantees that a semantically valid candidate cannot silently fail after block materialization.

## Jev feedback

Jev is integrated as an advisory map critic and style director.

The critic can label semantic candidate maps for:

- overall route quality
- exploration interest
- terrain naturalness
- visual rhythm
- originality
- dominant failure mode

The style director selects only profiles that the native materializer actually supports, currently:

- woodland_trail
- open_meadow
- scrub_route

Initial deployment should use Jev for candidate reranking rather than training the generator recursively. Synthetic fine-tuning is capped at roughly 25% of an epoch with authored maps remaining the majority.

Once enough labels exist, Jev preferences can also be distilled into a small on-device map-quality critic.

## Next generator architecture

1. Jev/Director specifies route requirements and style intent.
2. Graph grammar creates several macro-topology candidates.
3. Deterministic solver enforces seams, gates, callbacks and reachability.
4. Jev scores/reranks valid candidates.
5. Style-aware materializer converts semantic topology to a coherent native Red block family.
6. Optional masked diffusion may later inpaint unconstrained terrain regions around the locked graph skeleton.
7. Native tile-level validation remains the final authority.

This gives Infinite Red better authored-looking structure now without abandoning the diffusion experiment where it may ultimately be most useful.
