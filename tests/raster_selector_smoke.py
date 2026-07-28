"""Pure policy checks for the provisional selective-raster dispatcher."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from raster_selector import choose_geometry_mode


def main():
    small = choose_geometry_mode(160, 240, 3270, 0.8)
    assert small.mode == "legacy_exact", small

    short = choose_geometry_mode(250, 60, 3270, 0.8)
    assert short.mode == "rectangle", short

    dense = choose_geometry_mode(250, 240, 3270, 1.21)
    assert dense.mode == "rectangle", dense

    large = choose_geometry_mode(250, 240, 3270, 0.8)
    assert large.mode == "raster", large

    boundary = choose_geometry_mode(200, 240, 3270, 0.8)
    assert boundary.provisional_size_boundary
    assert boundary.mode == "raster", boundary

    invalid = choose_geometry_mode(250, 240, 0, float("nan"))
    assert invalid.mode == "rectangle", invalid
    print(
        "RASTER_SELECTOR_SMOKE_OK",
        f"n160={small.mode}",
        f"short={short.mode}",
        f"dense={dense.mode}",
        f"n250={large.mode}",
        f"n200_provisional={boundary.mode}",
    )


if __name__ == "__main__":
    main()
