#!/usr/bin/env python3
"""Capture and render 40 exact Bhadra bay-utilization timeline GIFs."""

from __future__ import annotations

import argparse
import colorsys
import concurrent.futures
import hashlib
import html
import json
import math
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = Path(__file__).with_name("capture_bhadra_solution.py")
EXPECTED_BHADRA_SHA256 = (
    "34c81f3698985561642cf771b10039df9825d8392cc5e2273ca846b5f02a488f"
)

WIDTH = 1280
HEIGHT = 820
BG = "#07111f"
PANEL = "#0d1b2d"
PANEL_EDGE = "#1d3550"
INK = "#edf4ff"
MUTED = "#91a3bb"
CYAN = "#35d3e6"
GREEN = "#42d392"
RED = "#ff647c"
AMBER = "#ffc857"
BAY_BG = "#f4f7fb"
BAY_EDGE = "#9dafc4"

UI_COLORS = [
    BG, PANEL, PANEL_EDGE, INK, MUTED, CYAN, GREEN, RED, AMBER,
    BAY_BG, BAY_EDGE, "#172a42", "#24344a", "#ffffff", "#000000",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=None)
def font(size: int, bold: bool = False):
    candidates = [
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold else
            "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold else
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def block_color(block_id: int) -> tuple[int, int, int]:
    # Thirty-two stable, high-contrast hues. IDs remain legible when colors repeat.
    hue = ((block_id % 32) * 0.61803398875) % 1.0
    saturation = 0.48 + 0.12 * ((block_id // 32) % 2)
    value = 0.90
    return tuple(
        int(round(channel * 255))
        for channel in colorsys.hsv_to_rgb(hue, saturation, value)
    )


def problem_path(number: int) -> Path:
    group = "train 2" if number <= 20 else "train"
    return ROOT / group / f"prob_{number}.json"


def parse_assignments(problem: dict, solution: dict) -> dict[int, dict]:
    records: dict[int, dict] = {}
    exits: dict[int, int] = {}
    for time_text, operations in solution.get("operations", {}).items():
        time_value = int(time_text)
        for operation in operations:
            block_id = int(operation["block_id"])
            if operation["type"] == "ENTRY":
                records[block_id] = {
                    "block_id": block_id,
                    "bay_id": int(operation["bay_id"]),
                    "x": int(round(operation.get("x", 0))),
                    "y": int(round(operation.get("y", 0))),
                    "orient_idx": int(operation.get("orient_idx", 0)),
                    "entry": time_value,
                }
            elif operation["type"] == "EXIT":
                exits[block_id] = time_value

    for block_id, assignment in records.items():
        block = problem["blocks"][block_id]
        assignment["exit"] = exits[block_id]
        assignment["release"] = int(block["release_time"])
        assignment["due"] = int(block["due_date"])
        assignment["tardy"] = max(0, assignment["exit"] - assignment["due"])
    if len(records) != len(problem["blocks"]):
        raise ValueError(
            f"operation stream assigns {len(records)}/{len(problem['blocks'])} blocks"
        )
    return records


def assignment_layers(problem: dict, assignment: dict) -> list[Polygon]:
    block = problem["blocks"][assignment["block_id"]]
    raw_layers = block["shape"][assignment["orient_idx"]]["layers"]
    if not raw_layers or not raw_layers[0]:
        return []
    ref_x, ref_y = raw_layers[0][0]
    layers: list[Polygon] = []
    for vertices in raw_layers:
        if not vertices:
            continue
        translated = [
            (
                float(x) - float(ref_x) + assignment["x"],
                float(y) - float(ref_y) + assignment["y"],
            )
            for x, y in vertices
        ]
        polygon = Polygon(translated)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if not polygon.is_empty and polygon.geom_type == "Polygon":
            layers.append(polygon)
    return layers


def polygon_parts(geometry) -> list[Polygon]:
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return []


def frame_times(records: dict[int, dict], maximum: int) -> list[int]:
    start = min(0, min(a["entry"] for a in records.values()))
    stop = max(a["exit"] for a in records.values())
    count = min(maximum, max(2, stop - start + 1))
    values = np.linspace(start, stop, count).round().astype(int)
    return sorted(set(int(value) for value in values))


def draw_bay(
    image: Image.Image,
    problem: dict,
    bay_id: int,
    active: list[dict],
    layers_by_block: dict[int, list[Polygon]],
    box: tuple[int, int, int, int],
    now: int,
) -> float:
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    bay = problem["bays"][bay_id]
    bay_width = float(bay["width"])
    bay_height = float(bay["height"])
    draw.rounded_rectangle(box, radius=12, fill=PANEL, outline=PANEL_EDGE, width=2)

    title_height = 34
    pad = 12
    available_width = max(1.0, x1 - x0 - 2 * pad)
    available_height = max(1.0, y1 - y0 - title_height - 2 * pad)
    scale = min(available_width / bay_width, available_height / bay_height)
    px0 = x0 + (x1 - x0 - bay_width * scale) / 2
    py0 = y0 + title_height + (available_height - bay_height * scale) / 2
    px1 = px0 + bay_width * scale
    py1 = py0 + bay_height * scale
    draw.rectangle((px0, py0, px1, py1), fill=BAY_BG, outline=BAY_EDGE, width=2)

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    def point(vertex: tuple[float, float]) -> tuple[float, float]:
        return px0 + vertex[0] * scale, py1 - vertex[1] * scale

    ground_area = 0.0
    # Upper layers first: they are real projected geometry, but deliberately
    # translucent so legal different-layer overlap is not mistaken for collision.
    for assignment in sorted(active, key=lambda item: item["block_id"]):
        block_id = assignment["block_id"]
        color = block_color(block_id)
        layers = layers_by_block[block_id]
        for layer in layers[1:]:
            for part in polygon_parts(layer):
                vertices = [point(v) for v in part.exterior.coords]
                overlay_draw.polygon(
                    vertices,
                    fill=color + (28,),
                    outline=color + (115,),
                    width=1,
                )

    for assignment in sorted(active, key=lambda item: item["block_id"]):
        block_id = assignment["block_id"]
        color = block_color(block_id)
        layers = layers_by_block[block_id]
        if not layers:
            continue
        ground = layers[0]
        ground_area += float(ground.area)
        overdue = now >= assignment["due"]
        outline = RED if overdue else "#233247"
        for part in polygon_parts(ground):
            vertices = [point(v) for v in part.exterior.coords]
            overlay_draw.polygon(
                vertices,
                fill=color + (205,),
                outline=outline,
                width=3 if overdue else 1,
            )
            for interior in part.interiors:
                overlay_draw.polygon(
                    [point(v) for v in interior.coords],
                    fill=(244, 247, 251, 255),
                )
        label_point = ground.representative_point()
        tx, ty = point((label_point.x, label_point.y))
        if ground.area * scale * scale >= 65:
            overlay_draw.text(
                (tx, ty),
                str(block_id),
                font=font(10, True),
                fill="#07111f",
                anchor="mm",
                stroke_width=1,
                stroke_fill=(255, 255, 255, 165),
            )
    image.paste(overlay, (0, 0), overlay)

    utilization = 100.0 * ground_area / max(1.0, bay_width * bay_height)
    draw = ImageDraw.Draw(image)
    draw.text(
        (x0 + 13, y0 + 9),
        f"BAY {bay_id}  ·  {int(bay_width)}×{int(bay_height)}",
        font=font(15, True),
        fill=INK,
    )
    draw.text(
        (x1 - 13, y0 + 10),
        f"{len(active)} blocks  ·  L0 {utilization:.1f}%",
        font=font(13),
        fill=CYAN,
        anchor="ra",
    )
    return utilization


def render_frame(
    problem: dict,
    records: dict[int, dict],
    layers_by_block: dict[int, list[Polygon]],
    verdict: dict,
    timelimit: float,
    now: int,
    horizon: int,
) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    name = str(problem.get("name", "instance")).upper()
    draw.text(
        (38, 28),
        f"{name} · BHADRA BAY-AREA REPLAY",
        font=font(27, True),
        fill=INK,
    )
    draw.text(
        (38, 66),
        (
            f"actual checker-feasible operation stream · {timelimit:g}s solve · "
            "solid = layer 0 · translucent = upper layers"
        ),
        font=font(14),
        fill=MUTED,
    )
    draw.text(
        (WIDTH - 38, 29),
        f"TIME {now:,}",
        font=font(28, True),
        fill=AMBER,
        anchor="ra",
    )

    track_x0, track_x1, track_y = 38, WIDTH - 38, 96
    draw.rounded_rectangle(
        (track_x0, track_y, track_x1, track_y + 10),
        radius=5,
        fill="#172a42",
    )
    progress = min(1.0, max(0.0, now / max(1, horizon)))
    draw.rounded_rectangle(
        (
            track_x0,
            track_y,
            track_x0 + progress * (track_x1 - track_x0),
            track_y + 10,
        ),
        radius=5,
        fill=AMBER,
    )

    bay_count = len(problem["bays"])
    columns = 1 if bay_count == 1 else 2
    rows = math.ceil(bay_count / columns)
    grid_left, grid_right = 34, WIDTH - 34
    grid_top, grid_bottom = 124, HEIGHT - 116
    gap = 14
    tile_width = (grid_right - grid_left - gap * (columns - 1)) / columns
    tile_height = (grid_bottom - grid_top - gap * (rows - 1)) / rows

    active_all = [
        assignment
        for assignment in records.values()
        if assignment["entry"] <= now < assignment["exit"]
    ]
    utilizations = []
    for bay_id in range(bay_count):
        row, column = divmod(bay_id, columns)
        x0 = round(grid_left + column * (tile_width + gap))
        y0 = round(grid_top + row * (tile_height + gap))
        x1 = round(x0 + tile_width)
        y1 = round(y0 + tile_height)
        active = [
            assignment
            for assignment in active_all
            if assignment["bay_id"] == bay_id
        ]
        utilizations.append(
            draw_bay(
                image,
                problem,
                bay_id,
                active,
                layers_by_block,
                (x0, y0, x1, y1),
                now,
            )
        )

    completed = [a for a in records.values() if a["exit"] <= now]
    completed_late = [a for a in completed if a["tardy"] > 0]
    realized_tardy = sum(a["tardy"] for a in completed)
    footer_y = HEIGHT - 91
    draw.line((38, footer_y - 12, WIDTH - 38, footer_y - 12), fill=PANEL_EDGE, width=2)
    draw.text(
        (38, footer_y),
        f"active {len(active_all):,}  ·  completed {len(completed):,}/{len(records):,}",
        font=font(17, True),
        fill=INK,
    )
    draw.text(
        (38, footer_y + 31),
        (
            f"late completions {len(completed_late):,}  ·  "
            f"realized tardy-days {realized_tardy:,}  ·  "
            f"mean L0 utilization {np.mean(utilizations):.1f}%"
        ),
        font=font(14),
        fill=MUTED,
    )
    draw.text(
        (WIDTH - 38, footer_y),
        f"objective {float(verdict['objective']):,.0f}",
        font=font(19, True),
        fill=GREEN,
        anchor="ra",
    )
    draw.text(
        (WIDTH - 38, footer_y + 31),
        (
            f"Z1 {float(verdict['obj1']):,.0f}  ·  "
            f"Z2 {float(verdict['obj2']):,.0f}  ·  "
            f"Z3 {float(verdict['obj3']):,.0f}"
        ),
        font=font(14),
        fill=MUTED,
        anchor="ra",
    )
    draw.text(
        (WIDTH / 2, HEIGHT - 18),
        "red outline = currently resident beyond due date",
        font=font(12),
        fill=RED,
        anchor="mm",
    )
    return image


def global_palette() -> Image.Image:
    colors = []
    for value in UI_COLORS:
        value = value.lstrip("#")
        colors.append(tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)))
    colors.extend(block_color(block_id) for block_id in range(32))
    swatches = Image.new("RGB", (len(colors), 1))
    for index, color in enumerate(colors):
        swatches.putpixel((index, 0), color)
    return swatches.quantize(colors=96, method=Image.Quantize.MEDIANCUT)


def render_payload(
    payload_path_text: str,
    output_dir_text: str,
    maximum_frames: int,
) -> dict:
    payload_path = Path(payload_path_text)
    output_dir = Path(output_dir_text)
    payload = json.loads(payload_path.read_text())
    problem = json.loads((ROOT / payload["problem_path"]).read_text())
    records = parse_assignments(problem, payload["solution"])
    layers_by_block = {
        block_id: assignment_layers(problem, assignment)
        for block_id, assignment in records.items()
    }
    times = frame_times(records, maximum_frames)
    horizon = max(a["exit"] for a in records.values())
    palette = global_palette()
    frames = [
        render_frame(
            problem,
            records,
            layers_by_block,
            payload["verdict"],
            payload["timelimit"],
            now,
            horizon,
        ).quantize(palette=palette, dither=Image.Dither.NONE)
        for now in times
    ]
    output = output_dir / f"{payload['problem']}_bay_timeline.gif"
    output.parent.mkdir(parents=True, exist_ok=True)
    durations = [120] * len(frames)
    durations[0] = 900
    durations[-1] = 1500
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return {
        "problem": payload["problem"],
        "gif": output.name,
        "gif_bytes": output.stat().st_size,
        "frames": len(frames),
        "horizon": horizon,
        "objective": payload["verdict"]["objective"],
        "elapsed": payload["elapsed"],
        "feasible": payload["verdict"]["feasible"],
    }


def capture_one(
    number: int,
    solver: Path,
    solution_dir: Path,
    timelimit: float,
    force: bool,
) -> Path:
    output = solution_dir / f"prob_{number}_bhadra.json"
    if output.is_file() and not force:
        try:
            payload = json.loads(output.read_text())
            if (
                payload.get("solver_sha256") == sha256(solver)
                and float(payload.get("timelimit", -1)) == timelimit
                and payload.get("verdict", {}).get("feasible") is True
            ):
                print(f"reuse checked solution prob_{number}", flush=True)
                return output
        except Exception:
            pass
    command = [
        sys.executable,
        str(CAPTURE),
        "--solver",
        str(solver),
        "--problem",
        str(problem_path(number)),
        "--timelimit",
        str(timelimit),
        "--output",
        str(output),
    ]
    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=max(timelimit + 90.0, timelimit * 2.0),
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"prob_{number} capture failed (rc={process.returncode})\n"
            f"stdout:\n{process.stdout[-3000:]}\n"
            f"stderr:\n{process.stderr[-3000:]}"
        )
    print(process.stdout.strip(), flush=True)
    return output


def write_index(output_dir: Path, manifest: list[dict], solver_hash: str) -> None:
    rows = []
    for item in sorted(manifest, key=lambda value: int(value["problem"].split("_")[-1])):
        rows.append(
            "<article>"
            f"<h2>{html.escape(item['problem'])}</h2>"
            f"<img src=\"{html.escape(item['gif'])}\" "
            f"alt=\"{html.escape(item['problem'])} Bhadra bay timeline\">"
            f"<p>objective {float(item['objective']):,.0f} · "
            f"{item['frames']} frames · horizon {item['horizon']} · "
            f"{item['gif_bytes'] / 1024 / 1024:.1f} MiB</p>"
            "</article>"
        )
    document = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bhadra · 40 bay-area timeline replays</title>
<style>
body {{ margin: 0; padding: 32px; background: #07111f; color: #edf4ff;
       font: 16px Arial, sans-serif; }}
header {{ max-width: 1100px; margin: 0 auto 32px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
         gap: 24px; }}
article {{ background: #0d1b2d; border: 1px solid #1d3550; border-radius: 16px;
           padding: 16px; }}
h1, h2 {{ margin: 0 0 12px; }}
h2 {{ font-size: 20px; }}
p {{ color: #91a3bb; }}
img {{ display: block; width: 100%; height: auto; border-radius: 9px; }}
code {{ color: #35d3e6; }}
</style>
<header>
  <h1>Bhadra · real bay-area usage through time</h1>
  <p>All 40 checker-feasible operation streams generated by solver
     <code>{solver_hash}</code>. Solid shapes are layer 0; translucent shapes
     are upper layers. Every frame is an actual integer-time schedule state.</p>
</header>
<main class="grid">{''.join(rows)}</main>
</html>
"""
    (output_dir / "index.html").write_text(document)
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "bhadra-bay-replay-manifest-v1",
                "solver_sha256": solver_hash,
                "cases": sorted(
                    manifest,
                    key=lambda value: int(value["problem"].split("_")[-1]),
                ),
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--solver",
        type=Path,
        default=ROOT / "submission" / "ogc_final_selector_candidate" / "myalgorithm.py",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts" / "bhadra_bay_timelines",
    )
    parser.add_argument("--timelimit", type=float, default=60.0)
    parser.add_argument("--solve-workers", type=int, default=2)
    parser.add_argument("--render-workers", type=int, default=4)
    parser.add_argument("--frames", type=int, default=72)
    parser.add_argument("--force-solves", action="store_true")
    args = parser.parse_args()

    solver = args.solver.resolve()
    output_dir = args.output_dir.resolve()
    solver_hash = sha256(solver)
    if solver_hash != EXPECTED_BHADRA_SHA256:
        raise SystemExit(
            "refusing to render a different solver: "
            f"expected {EXPECTED_BHADRA_SHA256}, got {solver_hash}"
        )
    if args.timelimit <= 0:
        raise SystemExit("--timelimit must be positive")

    solution_dir = output_dir / "solutions"
    solution_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"capture 40 cases · solver={solver_hash} · "
        f"timelimit={args.timelimit:g}s · workers={args.solve_workers}",
        flush=True,
    )
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, args.solve_workers)
    ) as pool:
        futures = {
            pool.submit(
                capture_one,
                number,
                solver,
                solution_dir,
                float(args.timelimit),
                args.force_solves,
            ): number
            for number in range(1, 41)
        }
        solution_paths = []
        for future in concurrent.futures.as_completed(futures):
            solution_paths.append(future.result())

    print(
        f"render 40 GIFs · maximum {args.frames} actual timeline frames each · "
        f"workers={args.render_workers}",
        flush=True,
    )
    # A thread pool is intentional here.  Some managed macOS environments
    # deny the SC_SEM_NSEMS_MAX query performed by ProcessPoolExecutor even
    # after the solver subprocesses have completed.  Pillow, NumPy, and
    # Shapely perform the expensive operations in native code, so threads
    # still provide useful rendering concurrency without another semaphore
    # pool.
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, args.render_workers)
    ) as pool:
        futures = [
            pool.submit(
                render_payload,
                str(path),
                str(output_dir),
                max(2, args.frames),
            )
            for path in sorted(solution_paths)
        ]
        manifest = []
        for future in concurrent.futures.as_completed(futures):
            item = future.result()
            manifest.append(item)
            print(
                f"rendered {item['problem']} · {item['frames']} frames · "
                f"{item['gif_bytes'] / 1024 / 1024:.1f} MiB",
                flush=True,
            )

    write_index(output_dir, manifest, solver_hash)
    print(f"wrote {output_dir / 'index.html'}")
    print(f"wrote {output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
