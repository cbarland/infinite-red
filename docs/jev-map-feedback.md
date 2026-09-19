# Jev feedback loop for map generation

Jev is useful here as a critic and style director, not as the spatial generator.

## 1. Critic / synthetic-data judge

The route generator emits compact semantic maps using four symbols: solid, mixed edge, open ground, and grass. Jev receives that ASCII layout plus deterministic metrics and world context, then makes batched typed judgments for:

- overall route quality;
- exploration interest;
- naturalness of terrain regions;
- visual rhythm;
- originality;
- dominant failure mode.

Initially these judgments should be used to **rerank candidates**. Generate many cheap maps and pick the highest-scoring valid candidate.

Every judgment is logged. Once the label set is large enough, high-scoring diverse maps can become a synthetic fine-tuning set.

Synthetic training is capped: keep human-authored maps as the majority of every fine-tuning epoch. This limits self-reinforcing model artifacts and Jev-specific taste collapse.

## 2. Style director

Jev also chooses a named style profile from topology plus world context, for example woodland trail, open meadow, rocky pass, riverside path, scrub route, or settlement approach.

It also chooses coarse materialization controls such as boundary density, grass-region pattern and path formality.

The deterministic materializer then maps those choices into compatible native Pokémon Red block families. Jev does **not** choose every individual block.

This creates a useful separation:

semantic topology model -> Jev style profile -> native block materializer

The topology model can therefore learn from multiple Gen 1 hacks even when their block IDs/tilesets differ, while Infinite Red always materializes using its own native Red vocabulary.

## Feedback-loop progression

1. Human-authored corpus only.
2. Generate K candidates and Jev-rerank at runtime/offline.
3. Accumulate Jev labels and human spot-checks.
4. Select only high-scoring, diverse, non-copylike candidates.
5. Fine-tune with roughly 75% authored / 25% synthetic examples.
6. Re-evaluate against held-out authored maps and visual contact sheets.
7. Only increase synthetic weight if quality improves without diversity collapse.
