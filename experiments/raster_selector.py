"""Pure selective-raster policy prototype.

This module does not import or invoke either geometry engine.  It isolates the
dispatch inputs and reasons so the completed 60-run comparison can calibrate
the unresolved size boundary without mixing policy and placement changes.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


LEGACY_EXACT_MAX_N = 160
PROVISIONAL_MIN_RASTER_N = 161
FORCED_DENSITY_LIMIT = 1.18
PASS_COST_SAFETY = 1.60
REFERENCE_PASS_SECONDS = 83.0
REFERENCE_N = 250.0
REFERENCE_BAY_CELLS = 3270.0


@dataclass(frozen=True)
class RasterDecision:
    mode: str
    reason: str
    estimated_pass_seconds: float
    required_remaining_seconds: float
    forced_density: float
    provisional_size_boundary: bool

    def to_dict(self):
        return asdict(self)


def estimate_pass_seconds(n_blocks, avg_bay_cells):
    """Measured first-order estimate from the n=250, 83-second prototype run."""
    if not math.isfinite(float(n_blocks)) or int(n_blocks) < 0:
        return float("inf")
    if not math.isfinite(float(avg_bay_cells)) or float(avg_bay_cells) <= 0.0:
        return float("inf")
    return (
        REFERENCE_PASS_SECONDS
        * max(1.0, float(n_blocks)) / REFERENCE_N
        * max(1.0, float(avg_bay_cells)) / REFERENCE_BAY_CELLS
    )


def peak_forced_density(problem, layer0_areas):
    """Mandatory-presence layer-0 density used by the selector.

    A zero-tardy schedule must contain block i during
    [D_i-P_i, R_i+P_i).  Summing minimum layer-0 areas over those intervals and
    dividing by total bay area gives the valid forced-density diagnostic used
    in the repository's lower-bound analysis.
    """
    blocks = problem.get("blocks", [])
    if len(layer0_areas) != len(blocks):
        raise ValueError("layer0_areas must contain one entry per block")
    events = []
    for bid, block in enumerate(blocks):
        duration = max(
            1, int(math.ceil(float(block["processing_time"]) - 1e-9))
        )
        lo = float(block["due_date"]) - duration
        hi = float(block["release_time"]) + duration
        if lo >= hi:
            continue
        area = float(layer0_areas[bid])
        if not math.isfinite(area) or area < 0.0:
            raise ValueError("layer0 areas must be finite and nonnegative")
        events.append((lo, 1, area))
        events.append((hi, 0, -area))
    load = peak = 0.0
    for _, _, delta in sorted(events):
        load += delta
        peak = max(peak, load)
    capacity = sum(
        float(bay["width"]) * float(bay["height"])
        for bay in problem.get("bays", [])
    )
    return peak / capacity if capacity > 0.0 else float("inf")


def choose_geometry_mode(
    n_blocks,
    remaining_seconds,
    avg_bay_cells,
    forced_density,
    min_raster_n=PROVISIONAL_MIN_RASTER_N,
):
    """Return ``legacy_exact``, ``raster``, or ``rectangle`` with a reason."""
    density = float(forced_density)
    remaining = float(remaining_seconds)
    estimated = estimate_pass_seconds(n_blocks, avg_bay_cells)
    required = PASS_COST_SAFETY * estimated
    provisional = int(min_raster_n) == PROVISIONAL_MIN_RASTER_N

    if int(n_blocks) <= LEGACY_EXACT_MAX_N:
        return RasterDecision(
            "legacy_exact",
            "legacy exact scan is measured better at n<=160",
            estimated, required, density, provisional,
        )
    if (
        not math.isfinite(density) or density < 0.0
        or not math.isfinite(remaining) or remaining < 0.0
        or not math.isfinite(estimated)
    ):
        return RasterDecision(
            "rectangle",
            "selector input is invalid or non-finite",
            estimated, required, density, provisional,
        )
    if int(n_blocks) < int(min_raster_n):
        return RasterDecision(
            "rectangle",
            "below calibrated raster size boundary",
            estimated, required, density, provisional,
        )
    if density > FORCED_DENSITY_LIMIT:
        return RasterDecision(
            "rectangle",
            "forced density exceeds the measured raster-safe regime",
            estimated, required, density, provisional,
        )
    if remaining < required:
        return RasterDecision(
            "rectangle",
            "insufficient remaining time to finish a raster construction pass",
            estimated, required, density, provisional,
        )
    return RasterDecision(
        "raster",
        "large-instance pass is affordable and density is acceptable",
        estimated, required, density, provisional,
    )
