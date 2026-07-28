# Bhadra bay-area timeline replays

This directory contains 40 animated GIFs generated from Bhadra's actual
checker-feasible operation streams on the supplied `prob_1` through `prob_40`
instances.

- Solver SHA-256:
  `34c81f3698985561642cf771b10039df9825d8392cc5e2273ca846b5f02a488f`
- Solve budget: 60 wall-clock seconds per instance.
- Every saved solution passed the official
  `ogc2026/baseline/utils.py::check_feasibility`.
- Every animation frame is a real integer-time state reconstructed from the
  returned `ENTRY` and `EXIT` operations. There is no interpolated placement.
- Solid polygons show layer 0. Translucent polygons show upper-layer
  projections. A red outline indicates a currently resident block whose due
  date has passed.
- GIFs contain 53–72 timeline frames depending on schedule horizon.

Open `index.html` to view all 40 animations in one browser page. The
`manifest.json` file records objectives, horizons, frame counts, sizes, and
provenance. The `solutions/` directory contains the 40 raw checked operation
streams used to render the animations.
