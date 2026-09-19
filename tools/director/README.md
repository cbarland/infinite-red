# Director model adapters

These are intentionally thin integration shims.

- `jev.py` calls Jev for batched typed decisions.
- `needle_story.py` calls an externally installed Needle 3 runner with Infinite Red's story-beat tool schema.

Infinite Red does **not** depend on or vendor the fuzzy-calc toolkit supplied during design. That package was used only to understand proven Jev/Needle invocation patterns.

Infinite Red also does not vendor Needle weights or runners. Configure them externally:

```bash
export OPENROUTER_API_KEY=...
export NEEDLE_BIN=/path/to/needle
export NEEDLE_MODEL=/path/to/needle3.cact
```

Jev is expected to handle the majority of semantic decisions. Needle is expected to handle structured story beats locally. Both outputs are advisory and must pass deterministic planning/materialization validation.
