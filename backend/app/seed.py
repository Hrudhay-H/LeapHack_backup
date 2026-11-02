"""Seed demo farmers/operators and ingest existing pipeline runs.

  uv run python -m app.seed

All people, phone numbers and PINs here are fictional demo data.
"""
from __future__ import annotations

from sqlmodel import Session

from . import security as sec
from .db import RUNS, engine, init_db
from .ingest import ingest_run
from .models import Farm, Farmer, Operator, Survey

DEMO_PIN = "1234"

FARMERS = [
    Farmer(id="MDY-001", name="Ramesh Gowda", village="Kikkeri, Mandya", language="kn",
           mobile="9000000001", access_mode="BOTH", collection_point="ಕೃಷಿ ಸೇವಾ ಕೇಂದ್ರ, ಕಿಕ್ಕೇರಿ"),
    Farmer(id="MDY-002", name="Lakshmamma", village="Maddur, Mandya", language="kn",
           mobile="9000000002", access_mode="ASSISTED", collection_point="ಮದ್ದೂರು FPO ಕಚೇರಿ"),
    Farmer(id="MDY-003", name="Suresh Kumar", village="Pandavapura, Mandya", language="en",
           mobile="9000000003", access_mode="DIGITAL", collection_point=""),
]
FARMS = [
    Farm(id="FARM-001", farmer_id="MDY-001", name="Kikkeri Paddy Plot A"),
    Farm(id="FARM-002", farmer_id="MDY-002", name="Maddur Paddy Plot"),
    Farm(id="FARM-003", farmer_id="MDY-003", name="Public-dataset maize plot (real UAV imagery)", crop="Maize"),
]
OPERATORS = [("OP-KIK", "Savitha", "Kikkeri Agri Service Centre"), ("OP-MAD", "Manjunath", "Maddur FPO Office")]
RUN_MAP = {
    "FARM-001": ("FARM-001-S01", "stressed"),
    "FARM-002": ("FARM-002-S01", "healthy"),
    "FARM-003": ("FARM-003-S01", "maize_rust"),
}


def main() -> None:
    init_db()
    with Session(engine) as s:
        for obj in [*FARMERS, *FARMS]:
            s.merge(obj)
        for oid, name, centre in OPERATORS:
            salt = sec.new_salt()
            s.merge(Operator(id=oid, name=name, centre=centre, pin_salt=salt, pin_hash=sec.hash_pin(DEMO_PIN, salt)))
        s.commit()
        for farm_id, (sid, run) in RUN_MAP.items():
            run_dir = RUNS / run
            if not (run_dir / "summary.json").exists():
                print(f"skip {sid}: no pipeline run at {run_dir}")
                continue
            survey = s.get(Survey, sid) or Survey(id=sid, farm_id=farm_id)
            s.add(survey); s.commit()
            rep = ingest_run(s, survey, run_dir)
            print(f"seeded {sid} -> {rep.id}")
    print("operators: OP-KIK / OP-MAD, PIN", DEMO_PIN, "| farmers: MDY-001, MDY-002 (assisted), MDY-003")


if __name__ == "__main__":
    main()
