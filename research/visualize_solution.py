#!/usr/bin/env python3
"""Research visualizer for OGC 2026 instance/solution pairs.

The official PyQt tester remains the final interactive viewer.  This script
produces reproducible PNGs and quantitative diagnostics suitable for comparing
many algorithm variants in batch/headless environments.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon, Rectangle
from shapely.geometry import Polygon
from shapely.ops import unary_union


COLORS = plt.colormaps["tab20"]


def assignments_from_solution(prob, solution):
    records = {}
    for t_str, ops in solution.get("operations", {}).items():
        t = int(t_str)
        for op in ops:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                records[bid] = {
                    "block_id": bid,
                    "bay_id": int(op["bay_id"]),
                    "x": int(op.get("x", 0)),
                    "y": int(op.get("y", 0)),
                    "orient_idx": int(op.get("orient_idx", 0)),
                    "entry": t,
                }
            elif bid in records:
                records[bid]["exit"] = t
    for bid, a in records.items():
        b = prob["blocks"][bid]
        a["exit"] = a.get("exit", a["entry"])
        a["due"] = int(b["due_date"])
        a["release"] = int(b["release_time"])
        a["tardy"] = max(0, a["exit"] - a["due"])
    return records


def translated_layers(prob, a):
    shape = prob["blocks"][a["block_id"]]["shape"][a["orient_idx"]]
    layers = shape["layers"]
    if not layers:
        return []
    ref_x, ref_y = layers[0][0]
    return [
        [(float(x) - ref_x + a["x"], float(y) - ref_y + a["y"])
         for x, y in layer]
        for layer in layers if layer
    ]


def union_area(prob, a):
    polys = []
    for layer in translated_layers(prob, a):
        p = Polygon(layer)
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty:
            polys.append(p)
    return float(unary_union(polys).area) if polys else 0.0


def utilization_series(prob, records):
    horizon = max((a["exit"] for a in records.values()), default=0)
    areas = {bid: union_area(prob, a) for bid, a in records.items()}
    series = [[0.0] * (horizon + 1) for _ in prob["bays"]]
    counts = [[0] * (horizon + 1) for _ in prob["bays"]]
    for bid, a in records.items():
        bay_area = (prob["bays"][a["bay_id"]]["width"]
                    * prob["bays"][a["bay_id"]]["height"])
        for t in range(a["entry"], a["exit"]):
            series[a["bay_id"]][t] += areas[bid] / bay_area
            counts[a["bay_id"]][t] += 1
    return series, counts


def print_diagnostics(prob, records, series, counts):
    tardy = sorted((a["tardy"] for a in records.values()), reverse=True)
    n = max(1, len(records))
    print(f"blocks={len(records)}  on_time={sum(x == 0 for x in tardy)}/{len(tardy)}"
          f" ({100*sum(x == 0 for x in tardy)/n:.1f}%)")
    print(f"total_tardiness={sum(tardy)}  max_tardiness={max(tardy, default=0)}")
    for j, bay in enumerate(prob["bays"]):
        peak = max(series[j], default=0.0)
        peak_t = max(range(len(series[j])), key=series[j].__getitem__) if series[j] else 0
        peak_n = max(counts[j], default=0)
        print(f"bay{j}: peak_union_util={100*peak:.1f}% at t={peak_t},"
              f" peak_blocks={peak_n}, size={bay['width']}x{bay['height']}")
    top = sorted(records.values(), key=lambda a: (-a["tardy"], a["due"]))[:10]
    print("top_tardy:",
          ", ".join(f"B{a['block_id']}={a['tardy']}d@bay{a['bay_id']}" for a in top))


def plot_dashboard(prob, records, series, output):
    fig = plt.figure(figsize=(17, 11), constrained_layout=True)
    gs = fig.add_gridspec(2, 1, height_ratios=[1.6, 1])
    ax_g = fig.add_subplot(gs[0])
    ax_u = fig.add_subplot(gs[1])

    rows = sorted(records.values(),
                  key=lambda a: (-a["tardy"], a["due"], a["block_id"]))[:45]
    for row, a in enumerate(reversed(rows)):
        color = COLORS(a["bay_id"] % 20)
        ax_g.barh(row, a["exit"] - a["entry"], left=a["entry"],
                  color=color, edgecolor="black", linewidth=0.3)
        if a["tardy"]:
            ax_g.barh(row, a["exit"] - max(a["due"], a["entry"]),
                      left=max(a["due"], a["entry"]),
                      color="#dc2626", alpha=0.75)
        ax_g.plot([a["due"], a["due"]], [row - .38, row + .38],
                  color="#7f1d1d", linewidth=.7)
    ax_g.set_yticks(range(len(rows)),
                    [f"B{a['block_id']} · bay{a['bay_id']} · T={a['tardy']}"
                     for a in reversed(rows)], fontsize=7)
    ax_g.set_title(f"{prob.get('name', 'instance')} — highest-tardiness blocks"
                   " (red = after due date)")
    ax_g.set_xlabel("time")
    ax_g.grid(axis="x", alpha=.2)

    for j, values in enumerate(series):
        ax_u.plot(range(len(values)), [100 * v for v in values],
                  label=f"Bay {j}", linewidth=1.8)
    ax_u.set_title("All-layer union-area utilization by bay")
    ax_u.set_xlabel("time")
    ax_u.set_ylabel("occupied union area / bay area (%)")
    ax_u.grid(alpha=.25)
    ax_u.legend(ncols=max(1, len(series)))
    fig.savefig(output, dpi=150)
    plt.close(fig)


def plot_peak_layout(prob, records, series, output):
    n_bays = len(prob["bays"])
    fig, axes = plt.subplots(n_bays, 1, figsize=(17, 3.2 * n_bays),
                             constrained_layout=True)
    if n_bays == 1:
        axes = [axes]
    for j, ax in enumerate(axes):
        bay = prob["bays"][j]
        peak_t = max(range(len(series[j])), key=series[j].__getitem__)
        active = [a for a in records.values()
                  if a["bay_id"] == j and a["entry"] <= peak_t < a["exit"]]
        ax.add_patch(Rectangle((0, 0), bay["width"], bay["height"],
                               facecolor="#f8fafc", edgecolor="black", linewidth=1.5))
        for a in active:
            for li, layer in enumerate(translated_layers(prob, a)):
                ax.add_patch(MplPolygon(
                    layer, closed=True,
                    facecolor=COLORS(a["block_id"] % 20),
                    edgecolor="black", linewidth=.35,
                    alpha=max(.25, .82 - .14 * li),
                ))
            x = sum(v[0] for v in translated_layers(prob, a)[0]) / len(
                translated_layers(prob, a)[0])
            y = sum(v[1] for v in translated_layers(prob, a)[0]) / len(
                translated_layers(prob, a)[0])
            ax.text(x, y, str(a["block_id"]), fontsize=6,
                    ha="center", va="center")
        ax.set_xlim(-1, bay["width"] + 1)
        ax.set_ylim(-1, bay["height"] + 1)
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(f"Bay {j} at peak-union time t={peak_t}: "
                     f"{100*series[j][peak_t]:.1f}% union utilization,"
                     f" {len(active)} blocks")
        ax.set_xlabel("x")
        ax.set_ylabel("y")
    fig.savefig(output, dpi=170)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("instance")
    parser.add_argument("solution")
    parser.add_argument("--output-dir", default="research/visuals")
    args = parser.parse_args()

    prob = json.loads(Path(args.instance).read_text())
    solution = json.loads(Path(args.solution).read_text())
    records = assignments_from_solution(prob, solution)
    series, counts = utilization_series(prob, records)
    print_diagnostics(prob, records, series, counts)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = prob.get("name", Path(args.instance).stem)
    dashboard = out_dir / f"{stem}_dashboard.png"
    layout = out_dir / f"{stem}_peak_layout.png"
    plot_dashboard(prob, records, series, dashboard)
    plot_peak_layout(prob, records, series, layout)
    print(f"wrote {dashboard}")
    print(f"wrote {layout}")


if __name__ == "__main__":
    main()

