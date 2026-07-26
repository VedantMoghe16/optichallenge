# Visual research workflow

## Interactive official Algorithm Tester

The tester settings are preconfigured for:

- Instance: `train/prob_25.json`
- Algorithm folder: `submission/`
- Time limit: 60 seconds

Create and activate the supplied environment, then launch the UI:

```bash
cd /Users/vedantmoghe/Downloads/optichallenge
conda env create -f ogc2026/ogc2026_env.yml
conda activate ogc2026
cd ogc2026/alg_tester
python alg_tester_app.py
```

The current base environment does not contain PyQt6, so the `ogc2026`
environment is required for the interactive app.

Research views:

1. In **Solution → Gantt**, sort by `Tardiness ↓`.
2. Red hatching shows the portion after each due date.
3. Step through operation times around the first large red cluster.
4. Toggle individual layers (`L0`, `L1`, …) in the bay view to distinguish
   true same-layer congestion from unused overhang space.
5. Compare peak layouts between algorithm versions rather than inspecting only
   the final day.
6. Save each solution JSON so comparisons use identical visualization logic.

## Headless/batch visualizer

For reproducible PNG output:

```bash
python research/visualize_solution.py \
  train/prob_25.json \
  research/solutions/prob_25_kestrel_improved_60s.json
```

It produces:

- a tardiness-sorted Gantt chart;
- union-area utilization curves by bay;
- irregular-polygon layouts at each bay's peak-utilization time;
- on-time percentage, maximum tardiness, peak utilization, and the ten most
  tardy blocks.

## Findings and resulting improvement

The original 10-second `prob_25` visualization showed:

- 52/100 blocks on time;
- 914 total tardy days;
- only 57.2% and 55.1% peak union-area utilization;
- long late-start cascades despite visible spatial holes.

The visual evidence identified geometry-oracle throughput and placement
selection—not merely priority order—as the immediate bottleneck. Two changes
were made:

1. exact placement now commits the earliest feasible true-polygon position;
2. positive-area collision is tested with the equivalent DE-9IM
   interior/interior-dimension-2 predicate, preserving legal edge contact while
   avoiding intersection-geometry construction.

On the same `prob_25` instance at 60 seconds this produced:

- objective 351,265;
- 58/100 blocks on time;
- 472 total tardy days;
- peak union utilization increased to 69.6% and 64.6%.

The next research neighborhood is controlled layer-aware under-tucking. It
should only be enabled after differential tests prove that its induced
ENTRY/EXIT nesting order always passes the official checker.
