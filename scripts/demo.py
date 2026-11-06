"""Generate a known-motion recording and review artifacts using the real engine.

Run from any working directory: python scripts/demo.py
Only synthetic images and portable, relative metadata are copied into web/demo.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
from worker import analyze, make_demo  # noqa: E402


def generate(output: Path, publish: Path) -> dict:
    """Run the analysis and publish only the viewer's synthetic inputs."""
    source = ROOT / "samples" / "synthetic-translation.npz"
    source.parent.mkdir(parents=True, exist_ok=True)
    make_demo(source)
    output.mkdir(parents=True, exist_ok=True)
    request = {
        "source": str(source),
        "output": str(output),
        "start": 5,
        "pairs": 12,
        "gap": 2,
        "pair_step": 3,
        "roi": [24, 24, 240, 130],
        "fps": 100,
        "mm_per_pixel": 0.1,
        "calibration_confirmed": True,
    }
    (output / "request.json").write_text(json.dumps(request), encoding="utf-8")
    analyze(request, output)
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    timeline = json.loads((output / "timeline.json").read_text(encoding="utf-8"))
    observed = result["median_dx_px_per_source_frame"]
    if observed is None or abs(observed - 2) > 0.15:
        raise RuntimeError(f"Synthetic translation check failed: {observed}")
    publish.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output / "timeline.json", publish / "timeline.json")
    for pair in timeline["pairs"]:
        for key in ("frame_preview", "frame_b_preview", "vector_preview"):
            shutil.copy2(output / pair[key], publish / pair[key])
    summary = {
        "kind": "synthetic validation",
        "seed": 731,
        "expected_dx_px_per_source_frame": 2.0,
        "expected_velocity_m_per_s": 0.02,
        "observed_dx_px_per_source_frame": observed,
        "observed_velocity_m_per_s": result["velocity_m_per_s"],
        "python": result["python"].split()[0],
        "opencv": result["opencv"],
        "numpy": result["numpy"],
        "note": "Generated texture translated +2 pixels per source frame. No research video or AI prediction is included.",
    }
    (publish / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runs" / "synthetic-demo")
    parser.add_argument("--publish", type=Path, default=ROOT / "web" / "demo")
    args = parser.parse_args()
    print(json.dumps(generate(args.output.resolve(), args.publish.resolve()), indent=2))


if __name__ == "__main__":
    main()
