"""Build the demo from this repository alone: real rice imagery with simulated stress, the visual-check reference,
pipeline runs for each farm's earlier survey, and the database.

  uv run python scripts/bootstrap_demo.py            # create everything that is missing
  uv run python scripts/bootstrap_demo.py --reset    # also delete and rebuild the SQLite database

No downloads needed: the prepared imagery ships in deploy/demo-data/. Optional extras (the real maize field, the full rice
dataset) are documented in the README. Run from anywhere; paths resolve from the repository root.
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

# Each farm's EARLIER survey (seeded as history); the survey-day simulator adds the next one.
EARLIER_SURVEYS = {"FARM-001-S01": "sim_b_prev", "FARM-002-S01": "sim_c_prev"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete data/agriscout.db first")
    a = ap.parse_args()

    sim, models, runs = Path("data/raw/sim"), Path("data/models"), Path("data/runs")
    if not (sim / "sim_b" / "rgb.tif").exists():
        shutil.copytree(ROOT / "deploy" / "demo-data" / "sim", sim, dirs_exist_ok=True)
        print("installed the prepared rice survey imagery from deploy/demo-data")

    model = models / "sim_rice.pt"
    if not model.exists():
        info = pipeline.train([sim / "sim_ref"], model)
        print("fitted the visual-check reference:", info["bank_size"], "patches")

    for survey_id, folder in EARLIER_SURVEYS.items():
        if not (runs / survey_id / "summary.json").exists():
            s = pipeline.run(sim / folder, model, runs / survey_id, survey_id=survey_id)
            print(f"analysed {survey_id} ({folder}): {s['summary']['hotspots_detected']} hotspot(s)")

    db = Path("data/agriscout.db")
    if a.reset and db.exists():
        db.unlink()
        print("deleted", db)
    from backend.app import seed

    seed.main()


if __name__ == "__main__":
    main()
