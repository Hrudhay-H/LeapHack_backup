from __future__ import annotations

import os
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RUNS = DATA / "runs"
RAW = DATA / "raw"
MODEL_PATH = DATA / "models" / "sim_rice.pt"  # visual-check reference fitted on a held-out real rice block
SIM_MODEL_PATH = MODEL_PATH
REPORTS = DATA / "reports"

DATA.mkdir(exist_ok=True)
DB_FILE = Path(os.environ.get("AGRISCOUT_DB", DATA / "agriscout.db"))
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    REPORTS.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    # create_all never alters existing tables: add columns introduced after a DB was first created.
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(survey)")}
        if "stage" not in cols:
            conn.exec_driver_sql("ALTER TABLE survey ADD COLUMN stage VARCHAR DEFAULT ''")


def get_session():
    with Session(engine) as s:
        yield s
