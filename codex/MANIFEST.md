# Codex artifact snapshot

This folder contains copies; the original workspace files were not moved.

## Improved solver

- `submission/slot_b/myalgorithm.py` — the improved working solver.
- `submission/slot_b/myalgorithm_working_latest.py` — the latest shared source
  snapshot, including the subsequent dormant-layer storage optimization.
- `submission/slot_b/README.md` — method and validation notes.
- `submission/ogc2026_kestrel_slot_b.zip` — packaged submission candidate.
- `submission/packaged_snapshot/` — exact source and README contained in that
  zip, retained so archive provenance is unambiguous.

These three are **shared Claude + Codex artifacts**: they started from the
Claude-developed Kestrel solver and were extended/tested by Codex. Identical
copies therefore also appear under `claude/`.

The zip contains the earlier source in `packaged_snapshot/`. The separately named
`myalgorithm_working_latest.py` mirrors the current working source without
repackaging it from this side conversation.

## Codex-only research and validation

- `research/benchmark_solver.py`
- `research/test_layer_true_predicate.py`
- `research/TASK-layer-true-results.md`
- `research/layer_true_differential_100k.log`
- `research/*sweep*.csv` and `research/*set1*.csv`
- `research/solutions/*_slot_b_60s.json`
- `research/visuals/slot_b/*.png`

Note: `slot_b_set1_10s.csv` records the interrupted exploratory sweep and is
retained for provenance; use the checker-verified 60-second solution files and
the completed 2.5-second sweeps for decisions.
