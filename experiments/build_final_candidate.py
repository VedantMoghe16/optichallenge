"""Build the integrated one-file final-candidate ZIP.

This does not modify the tracked hardened baseline.  It materializes the
current guarded algorithm with W1/W2/W3 enabled, packages the raster dependency,
inside the one permitted Python file, and verifies archive structure and source
hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments" / "myalgorithm_lns_prototype.py"
KERNEL = ROOT / "submission" / "raster_kernel.py"
DEFAULT_OUTPUT = ROOT / "submission" / "ogc_final_candidate_onefile.zip"
SWITCHES = ("ADVANCED_LNS", "SELECTIVE_RASTER", "LOOSE_POLISH")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="destination ZIP (default: %(default)s)",
    )
    args = parser.parse_args()
    output = args.output.resolve()

    text = SOURCE.read_text()
    for name in SWITCHES:
        marker = f"{name} = False"
        if text.count(marker) != 1:
            raise RuntimeError(f"{name} marker is not unique")
        text = text.replace(marker, f"{name} = True", 1)
    if "CP_SAT_REPAIR = False" not in text:
        raise RuntimeError("CP-SAT must remain disabled in the final candidate")

    # The submission portal accepts exactly one Python file in the ZIP.
    # Materialise raster_kernel as an in-memory module so the guarded imports
    # in myalgorithm.py keep working without a second archive member.  Failure
    # to import an optional numerical dependency removes the embedded module
    # and preserves the solver's existing fail-closed legacy fallback.
    future = "from __future__ import annotations\n"
    if text.count(future) != 1:
        raise RuntimeError("future-import anchor is not unique")
    kernel_source = KERNEL.read_text()
    bootstrap = (
        "\n# Embedded optional raster kernel (single-file submission).\n"
        "import sys as _raster_sys\n"
        "import types as _raster_types\n"
        f"_RASTER_KERNEL_SOURCE = {kernel_source!r}\n"
        "try:\n"
        "    _raster_module = _raster_types.ModuleType('raster_kernel')\n"
        "    _raster_module.__file__ = '<embedded raster_kernel>'\n"
        "    _raster_sys.modules['raster_kernel'] = _raster_module\n"
        "    exec(compile(_RASTER_KERNEL_SOURCE,\n"
        "                 '<embedded raster_kernel>', 'exec'),\n"
        "         _raster_module.__dict__)\n"
        "except Exception:\n"
        "    _raster_sys.modules.pop('raster_kernel', None)\n"
        "\n"
    )
    text = text.replace(future, future + bootstrap, 1)

    with tempfile.TemporaryDirectory(prefix="ogc_submission2_") as tmp:
        stage = Path(tmp)
        candidate = stage / "myalgorithm.py"
        candidate.write_text(text)

        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.write(candidate, arcname="myalgorithm.py")

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        expected = ["myalgorithm.py"]
        if names != expected:
            raise RuntimeError(f"unexpected ZIP structure: {names}")
        if any("/" in name for name in names):
            raise RuntimeError("ZIP contains nested paths")
        if archive.read("myalgorithm.py") != text.encode():
            raise RuntimeError("candidate source changed during packaging")
        manifest = {
            "output": str(output),
            "size_bytes": output.stat().st_size,
            "files": names,
            "myalgorithm_sha256": sha256(archive.read("myalgorithm.py")),
            "embedded_raster_kernel_sha256": sha256(KERNEL.read_bytes()),
            "switches": {
                "advanced_lns": True,
                "selective_raster": True,
                "loose_polish": True,
                "cp_sat": False,
                "lns_min_blocks": 100,
                "lns_min_limit": 90.0,
            },
        }
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
