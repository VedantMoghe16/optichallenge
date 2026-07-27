# Kestrel versus raster bay replay

`prob38_kestrel_vs_raster.gif` replays two checker-feasible solutions of
`train/prob_38.json`, generated sequentially with a 180-second limit.

- **Kestrel/base:** continuous contact candidates followed by exact Shapely
  confirmation.
- **Raster:** conservative quarter-unit (`S=4`) occupancy cells, a batch map
  over every integer placement, then the same exact Shapely confirmation.

The colored polygons are reconstructed from the exact `ENTRY` operations,
chosen orientation and integer coordinates. Cyan cells in the raster panels
are computed by `submission/raster_kernel.py`; they are not decorative.

Rebuild:

```bash
/opt/anaconda3/bin/python codex/visualizations/render_decoder_comparison.py
```

The saved operation streams are under `codex/visualizations/data/` and can
also be opened in the supplied Algorithm Tester UI.
