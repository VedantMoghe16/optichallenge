#!/usr/bin/env python3
"""Render an exact schedule replay comparing Kestrel and raster decoding.

The GIF uses the submitted operation streams rather than an illustrative
packing.  Continuous polygon fills are reconstructed from the chosen
orientation and integer placement.  For the raster arm, the cyan background
is the actual conservative S=4 cell coverage produced by raster_kernel.py.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "submission"))
from raster_kernel import rasterize_polygon  # noqa: E402


WIDTH, HEIGHT = 1600, 980
BG = "#07111f"
PANEL = "#0d1b2d"
INK = "#e7eef8"
MUTED = "#91a3bb"
CYAN = "#35d3e6"
GREEN = "#42d392"
RED = "#ff647c"
AMBER = "#ffc857"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def load_assignments(problem: dict, solution: dict):
    records = {}
    for t_str, operations in solution["operations"].items():
        t = int(t_str)
        for op in operations:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                records[bid] = {
                    "block_id": bid,
                    "bay_id": int(op["bay_id"]),
                    "x": int(op["x"]),
                    "y": int(op["y"]),
                    "orient_idx": int(op["orient_idx"]),
                    "entry": t,
                }
            elif bid in records:
                records[bid]["exit"] = t
    for bid, a in records.items():
        block = problem["blocks"][bid]
        a["exit"] = int(a["exit"])
        a["due"] = int(block["due_date"])
        a["tardy"] = max(0, a["exit"] - a["due"])
    return records


def union_polygon(problem: dict, assignment: dict):
    bid = assignment["block_id"]
    shape = problem["blocks"][bid]["shape"][assignment["orient_idx"]]
    layers = shape["layers"]
    ref_x, ref_y = layers[0][0]
    polys = []
    for layer in layers:
        points = [
            (
                float(x) - float(ref_x) + assignment["x"],
                float(y) - float(ref_y) + assignment["y"],
            )
            for x, y in layer
        ]
        p = Polygon(points)
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty:
            polys.append(p)
    return unary_union(polys)


def color_for_block(bid: int):
    hue = (bid * 0.61803398875) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.62, 0.96)
    return int(r * 255), int(g * 255), int(b * 255)


def polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return []


def mask_for_bay(active, polygons, bay, scale=4):
    rows, cols = int(bay["height"]) * scale, int(bay["width"]) * scale
    occupancy = np.zeros((rows, cols), dtype=bool)
    for a in active:
        p = polygons[a["block_id"]]
        for part in polygon_parts(p):
            mask, ox, oy = rasterize_polygon(part, scale)
            r0, c0 = oy, ox
            r1, c1 = r0 + mask.shape[0], c0 + mask.shape[1]
            sr0, sc0 = max(0, r0), max(0, c0)
            sr1, sc1 = min(rows, r1), min(cols, c1)
            if sr0 >= sr1 or sc0 >= sc1:
                continue
            mr0, mc0 = sr0 - r0, sc0 - c0
            occupancy[sr0:sr1, sc0:sc1] |= mask[
                mr0:mr0 + (sr1 - sr0), mc0:mc0 + (sc1 - sc0)
            ]
    return occupancy


def draw_bay(
    image,
    problem,
    bay_id,
    active,
    polygons,
    box,
    raster=False,
):
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    bay = problem["bays"][bay_id]
    width, height = float(bay["width"]), float(bay["height"])
    pad = 10
    sx = (x1 - x0 - 2 * pad) / width
    sy = (y1 - y0 - 2 * pad) / height
    scale = min(sx, sy)
    px0 = x0 + (x1 - x0 - width * scale) / 2
    py0 = y0 + (y1 - y0 - height * scale) / 2
    px1, py1 = px0 + width * scale, py0 + height * scale
    draw.rounded_rectangle(box, radius=13, fill=PANEL, outline="#1d3550", width=2)
    draw.rectangle((px0, py0, px1, py1), fill="#f4f7fb", outline="#a9b7c9", width=2)

    if raster:
        mask = mask_for_bay(active, polygons, bay, 4)
        rgba = np.zeros((mask.shape[0], mask.shape[1], 4), dtype=np.uint8)
        rgba[mask] = (53, 211, 230, 95)
        layer = Image.fromarray(rgba, "RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        layer = layer.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.NEAREST,
        )
        image.alpha_composite(layer, (round(px0), round(py0)))

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    def point(v):
        return px0 + v[0] * scale, py1 - v[1] * scale

    for a in sorted(active, key=lambda item: item["block_id"]):
        bid = a["block_id"]
        rgb = color_for_block(bid)
        outline = RED if a["tardy"] else "#24344a"
        for part in polygon_parts(polygons[bid]):
            exterior = [point(v) for v in part.exterior.coords]
            odraw.polygon(exterior, fill=rgb + (165,), outline=outline, width=2)
            for ring in part.interiors:
                odraw.polygon([point(v) for v in ring.coords], fill=(244, 247, 251, 255))
        c = polygons[bid].representative_point()
        tx, ty = point((c.x, c.y))
        if polygons[bid].area >= 14:
            odraw.text(
                (tx, ty),
                str(bid),
                font=font(12, True),
                fill="#07111f",
                anchor="mm",
                stroke_width=1,
                stroke_fill=(255, 255, 255, 110),
            )
    image.alpha_composite(overlay)

    union_area = sum(polygons[a["block_id"]].area for a in active)
    utilization = 100 * union_area / (width * height)
    draw = ImageDraw.Draw(image)
    draw.text(
        (x0 + 14, y0 + 10),
        f"Bay {bay_id}  ·  {int(width)}×{int(height)}",
        font=font(17, True),
        fill=INK,
    )
    draw.text(
        (x1 - 14, y0 + 11),
        f"{len(active)} active  ·  {utilization:.1f}% union fill",
        font=font(15),
        fill=CYAN if raster else MUTED,
        anchor="ra",
    )


def stats_at(records, t):
    finished = [a for a in records.values() if a["exit"] <= t]
    late = [a for a in finished if a["tardy"]]
    tardy_days = sum(a["tardy"] for a in finished)
    return len(finished), len(late), tardy_days


def draw_metric_bar(draw, x, y, width, label, value, maximum, color):
    draw.text((x, y), label, font=font(16), fill=MUTED)
    draw.rounded_rectangle((x + 170, y + 3, x + 170 + width, y + 19),
                           radius=8, fill="#172a42")
    fill = width * min(1.0, value / max(1, maximum))
    draw.rounded_rectangle((x + 170, y + 3, x + 170 + fill, y + 19),
                           radius=8, fill=color)
    draw.text((x + 180 + width, y), f"{value:,}", font=font(16, True),
              fill=INK, anchor="la")


def render_frame(problem, arms, polygons, t, t_max):
    image = Image.new("RGBA", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.text((48, 34), "PROB_38 · BAY-AREA OPTIMIZATION REPLAY",
              font=font(31, True), fill=INK)
    draw.text(
        (48, 76),
        "Same instance, 180 s each · exact saved operation streams · red outline = tardy block",
        font=font(18),
        fill=MUTED,
    )
    draw.text((WIDTH - 50, 38), f"DAY {t:03d}", font=font(32, True),
              fill=AMBER, anchor="ra")
    track_x0, track_x1, track_y = 48, WIDTH - 50, 122
    draw.rounded_rectangle((track_x0, track_y, track_x1, track_y + 12),
                           radius=6, fill="#172a42")
    progress = (t - 0) / max(1, t_max)
    draw.rounded_rectangle(
        (track_x0, track_y, track_x0 + progress * (track_x1 - track_x0), track_y + 12),
        radius=6,
        fill=AMBER,
    )

    rows = [
        ("KESTREL / BASE", "continuous contact candidates → exact Shapely confirmation", False),
        ("RASTER S=4", "batch integer feasible-map → exact Shapely confirmation", True),
    ]
    row_y = [158, 478]
    margin, gap = 44, 20
    tile_w = (WIDTH - 2 * margin - 2 * gap) / 3
    for arm_index, (title, subtitle, raster) in enumerate(rows):
        records = arms[arm_index]["records"]
        y = row_y[arm_index]
        draw.text((margin, y), title, font=font(23, True),
                  fill=CYAN if raster else INK)
        draw.text((margin + 250, y + 3), subtitle, font=font(16), fill=MUTED)
        for bay_id in range(3):
            active = [
                a for a in records.values()
                if a["bay_id"] == bay_id and a["entry"] <= t < a["exit"]
            ]
            bx0 = margin + bay_id * (tile_w + gap)
            draw_bay(
                image,
                problem,
                bay_id,
                active,
                polygons[arm_index],
                (round(bx0), y + 38, round(bx0 + tile_w), y + 292),
                raster=raster,
            )

    footer_y = 805
    draw.line((48, footer_y - 15, WIDTH - 48, footer_y - 15), fill="#1d3550", width=2)
    max_tardy = max(arms[0]["obj1"], arms[1]["obj1"])
    for idx, arm in enumerate(arms):
        x = 48 + idx * 775
        finished, late, td = stats_at(arm["records"], t)
        label = "KESTREL" if idx == 0 else "RASTER"
        label_color = INK if idx == 0 else CYAN
        draw.text((x, footer_y), label, font=font(21, True), fill=label_color)
        draw.text(
            (x + 125, footer_y + 1),
            f"objective {arm['objective']:,}  ·  final Z1 {arm['obj1']:,}",
            font=font(18),
            fill=INK,
        )
        draw.text(
            (x, footer_y + 40),
            f"completed {finished}/250  ·  late completions {late}  ·  realized tardy-days {td:,}",
            font=font(16),
            fill=MUTED,
        )
        draw_metric_bar(draw, x, footer_y + 76, 410, "final tardy-days", arm["obj1"],
                        max_tardy, RED if idx == 1 and arm["obj1"] > arms[0]["obj1"] else GREEN)

    delta = 100 * (arms[1]["objective"] - arms[0]["objective"]) / arms[0]["objective"]
    verdict = f"This 180 s replay: raster {delta:+.2f}% vs Kestrel"
    draw.rounded_rectangle((530, 932, 1070, 970), radius=18,
                           fill="#311b29" if delta > 0 else "#12342a")
    draw.text((800, 951), verdict, font=font(19, True),
              fill=RED if delta > 0 else GREEN, anchor="mm")
    # Keep frames in RGB until GIF encoding.  Quantising every frame
    # independently here can assign identical palette indices to different
    # colours, which makes Pillow's GIF optimiser incorrectly coalesce scenes.
    return image.convert("RGB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path,
                        default=ROOT / "train" / "prob_38.json")
    parser.add_argument("--kestrel", type=Path,
                        default=Path(__file__).parent / "data" / "prob38_kestrel_180s.json")
    parser.add_argument("--raster", type=Path,
                        default=Path(__file__).parent / "data" / "prob38_raster_180s.json")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parent / "prob38_kestrel_vs_raster.gif")
    parser.add_argument("--frames", type=int, default=72)
    args = parser.parse_args()

    problem = json.loads(args.instance.read_text())
    solutions = [json.loads(args.kestrel.read_text()), json.loads(args.raster.read_text())]
    records = [load_assignments(problem, sol) for sol in solutions]
    objectives = [
        {"objective": 74_153_157, "obj1": 5_457},
        {"objective": 78_249_764, "obj1": 5_738},
    ]
    arms = [
        {**objectives[i], "records": records[i]}
        for i in range(2)
    ]
    polygons = [
        {bid: union_polygon(problem, a) for bid, a in rec.items()}
        for rec in records
    ]
    t_max = max(a["exit"] for rec in records for a in rec.values())
    event_times = sorted({
        0,
        t_max,
        *(a["entry"] for rec in records for a in rec.values()),
        *(a["exit"] for rec in records for a in rec.values()),
    })
    wanted = min(args.frames, len(event_times))
    indices = np.linspace(0, len(event_times) - 1, wanted).round().astype(int)
    times = [event_times[i] for i in sorted(set(indices))]

    rendered = []
    for index, t in enumerate(times):
        print(f"render {index + 1:02d}/{len(times)} day={t}", flush=True)
        rendered.append(render_frame(problem, arms, polygons, t, t_max))
    rendered = [rendered[0]] * 8 + rendered + [rendered[-1]] * 12
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered[0].save(
        args.output,
        save_all=True,
        append_images=rendered[1:],
        duration=115,
        loop=0,
        optimize=False,
        disposal=2,
    )
    print(f"wrote {args.output} ({args.output.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
