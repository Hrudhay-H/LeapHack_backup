"""Build the demo from nothing but this repository: synthetic fields, the PatchCore reference, pipeline runs and the database.

  uv run python scripts/bootstrap_demo.py            # create everything missing
  uv run python scripts/bootstrap_demo.py --reset    # also delete and rebuild the SQLite database
  uv run python scripts/bootstrap_demo.py --sim      # also set up the rice survey-day simulator from deploy/demo-data

Needs no downloads. Real-imagery extras (maize field, rice survey-day simulator) are separate and documented in the README.
Run from anywhere; paths are resolved from the repository root.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from agriscout_ml import pipeline  # noqa: E402
from agriscout_ml.synth import SynthConfig, default_patches, generate  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete data/agriscout.db first")
    ap.add_argument("--sim", action="store_true", help="install the shipped rice survey-day simulator data and fit its reference")
    a = ap.parse_args()

    raw, models, runs = Path("data/raw/synthetic"), Path("data/models"), Path("data/runs")
    fields = {
        "ref1": SynthConfig(seed=1),
        "ref2": SynthConfig(seed=2),
        "stressed": SynthConfig(seed=7, patches=default_patches()),
        "healthy": SynthConfig(seed=11),
    }
    for name, cfg in fields.items():
        if not (raw / name / "rgb.tif").exists():
            generate(raw / name, cfg)
            print("generated synthetic field", name)

    model = models / "patchcore.pt"
    if not model.exists():
        info = pipeline.train([raw / "ref1", raw / "ref2"], model)
        print("fitted PatchCore reference:", info["bank_size"], "patches")

    for name in ("stressed", "healthy"):
        if not (runs / name / "summary.json").exists():
            s = pipeline.run(raw / name, model, runs / name, survey_id=name)
            print(f"ran pipeline on {name}: {s['summary']['hotspots_detected']} hotspot(s)")

    if a.sim:
        shipped, sim = ROOT / "deploy" / "demo-data" / "sim", raw.parent / "sim"
        if not (sim / "sim_a" / "rgb.tif").exists():
            shutil.copytree(shipped, sim, dirs_exist_ok=True)
            print("installed simulator imagery from deploy/demo-data")
        sim_model = models / "sim_rice.pt"
        if not sim_model.exists():
            info = pipeline.train([sim / "sim_ref"], sim_model)
            print("fitted simulator reference:", info["bank_size"], "patches")

    db = Path("data/agriscout.db")
    if a.reset and db.exists():
        db.unlink()
        print("deleted", db)
    from backend.app import seed

    seed.main()


if __name__ == "__main__":
    main()
