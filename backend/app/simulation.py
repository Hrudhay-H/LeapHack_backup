"""Survey-day simulation: the next drone survey arrives for three farms, built from REAL imagery with SIMULATED stress.

Imagery comes from `agriscout_ml.simulate` (the healthy site of the Thai UAV rice dataset, CC BY 4.0). Each farm already has
history from the seed, except the newly added one:

  FARM-001  second survey: the patch found last time has grown and spread, and a new one has appeared
  FARM-002  second survey: clean last time, it now has an elongated strip and a patch
  FARM-003  first survey for a newly added farm: untouched real imagery

The stress is added to real imagery, not real pest damage. That is recorded in each survey's metadata and repeated in the
UI and PDF. Prepare the imagery once with `uv run python scripts/bootstrap_demo.py`.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException
from sqlmodel import Session, select

from .db import RAW, RUNS, SIM_MODEL_PATH
from .ingest import analyze_background
from .models import AccessLog, AccessRequest, Farm, Farmer, Hotspot, Report, SmsMessage, Survey

STAGES = [
    ("received", "Imagery received"),
    ("quality", "Quality and alignment checks"),
    ("index", "Vegetation-index analysis"),
    ("visual", "Visual texture check (experimental)"),
    ("hotspots", "Hotspot extraction"),
    ("render", "Maps and layers"),
    ("report", "PDF report generated"),
    ("done", "Farmer notified by SMS"),
]

SIM_FARMS = [
    {"farm_id": "FARM-001", "survey_id": "FARM-001-S02", "dir": "sim/sim_b"},
    {"farm_id": "FARM-002", "survey_id": "FARM-002-S02", "dir": "sim/sim_c"},
    {"farm_id": "FARM-003", "survey_id": "FARM-003-S01", "dir": "sim/sim_a"},
]
PREPARE_CMD = "uv run python scripts/bootstrap_demo.py"


def missing_inputs() -> list[str]:
    miss = [f["dir"] for f in SIM_FARMS if not (RAW / f["dir"] / "rgb.tif").exists()]
    if not SIM_MODEL_PATH.exists():
        miss.append(SIM_MODEL_PATH.name)
    return miss


def _run_all(farms: list[dict]) -> None:
    for f in farms:  # one after another: CPU-bound, and SQLite is single-writer
        analyze_background(f["survey_id"], str(RAW / f["dir"]), model_path=SIM_MODEL_PATH, notify=True)


def start(session: Session, bg: BackgroundTasks) -> dict:
    miss = missing_inputs()
    if miss:
        raise HTTPException(409, f"Simulation imagery not prepared ({', '.join(miss)}). Run: {PREPARE_CMD}")
    ids = [f["survey_id"] for f in SIM_FARMS]
    if any(session.get(Survey, i) for i in ids):
        raise HTTPException(409, "This survey day has already run. Reset the simulation first.")
    for f in SIM_FARMS:
        if not session.get(Farm, f["farm_id"]):
            raise HTTPException(409, f"Farm {f['farm_id']} is missing. Run: {PREPARE_CMD}")
    for f in SIM_FARMS:
        session.add(Survey(id=f["survey_id"], farm_id=f["farm_id"], status="PROCESSING", stage="received", data_source="pending"))
    session.commit()
    bg.add_task(_run_all, SIM_FARMS)
    return {"started": ids}


def _survey_meta(dir_: str) -> dict:
    p = RAW / dir_ / "survey.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _context(session: Session, farm_id: str, survey_id: str) -> str:
    earlier = [
        s for s in session.exec(select(Survey).where(Survey.farm_id == farm_id)).all()
        if s.id != survey_id and s.status == "COMPLETED"
    ]
    if not earlier:
        return "First survey for a newly added farm."
    last = max(earlier, key=lambda s: s.created_at)
    n = (last.summary.get("summary") or {}).get("hotspots_detected")
    found = "no anomaly" if n == 0 else f"{n} hotspot{'s' if n != 1 else ''}"
    return f"Follow-up survey. The previous one ({last.created_at:%d %b %Y}) found {found}."


def status(session: Session) -> dict:
    out = []
    for f in SIM_FARMS:
        farm = session.get(Farm, f["farm_id"])
        farmer = session.get(Farmer, farm.farmer_id) if farm else None
        sv = session.get(Survey, f["survey_id"])
        planted = _survey_meta(f["dir"]).get("planted") or []
        row = {
            "farm_id": f["farm_id"],
            "farm_name": farm.name if farm else f["farm_id"],
            "farmer_id": farmer.id if farmer else None,
            "farmer": farmer.name if farmer else None,
            "village": farmer.village if farmer else None,
            "language": farmer.language if farmer else None,
            "access_mode": farmer.access_mode if farmer else None,
            "input": {
                "source": "Real UAV orthomosaic of a rice research station (Thai UAV rice dataset, CC BY 4.0)",
                "context": _context(session, f["farm_id"], f["survey_id"]) if farm else "",
                "simulated_stress": bool(planted),
                "planted_patches": [
                    {"name": p.get("name"), "radius_m": p.get("radius_m"), "severity": p.get("severity")} for p in planted
                ],
            },
            "survey_id": f["survey_id"] if sv else None,
            "status": sv.status if sv else "NOT_STARTED",
            "stage": sv.stage if sv else "",
            "error": sv.error if sv else None,
            "result": None,
        }
        if sv and sv.status == "COMPLETED":
            sm = sv.summary or {}
            res = sm.get("summary") or {}
            chk = sm.get("synthetic_check") or {}
            rep = session.exec(select(Report).where(Report.survey_id == sv.id).order_by(Report.version.desc())).first()
            sms = session.exec(
                select(SmsMessage).where(
                    SmsMessage.to_mobile == farmer.mobile, SmsMessage.kind == "NOTIFY", SmsMessage.at >= sv.created_at
                )
            ).first()
            patches = chk.get("patches", [])
            row["result"] = {
                "hotspots": res.get("hotspots_detected"),
                "suspicious_percent": res.get("suspicious_area_percent"),
                "valid_crop_area_sqm": res.get("valid_crop_area_sqm"),
                "status": res.get("status"),
                "patches_found": sum(1 for p in patches if p.get("detected")) if chk else None,
                "patches_total": len(patches) if chk else None,
                "pixel_recall": chk.get("pixel_recall"),
                "pixel_precision": chk.get("pixel_precision"),
                "report_id": rep.id if rep else None,
                "notified": sms is not None,
                "sms": sms.body if sms else None,
            }
        out.append(row)
    started = any(r["status"] != "NOT_STARTED" for r in out)
    # COMPLETED is set when hotspots are stored, before the PDF is built and the SMS sent: finished means stage "done".
    finished = started and all(r["status"] == "FAILED" or (r["status"] == "COMPLETED" and r["stage"] == "done") for r in out)
    miss = missing_inputs()
    return {
        "stages": [{"key": k, "label": lbl} for k, lbl in STAGES],
        "farms": out,
        "started": started,
        "finished": finished,
        "ready": not miss,
        "missing": miss,
        "prepare_command": PREPARE_CMD,
    }


def reset(session: Session) -> dict:
    """Remove the simulated survey day; each farm returns to its seeded history."""
    ids = [f["survey_id"] for f in SIM_FARMS]
    surveys = [s for s in (session.get(Survey, i) for i in ids) if s]
    first = min((s.created_at for s in surveys), default=None)
    reports = session.exec(select(Report).where(Report.survey_id.in_(ids))).all()
    rep_ids = [r.id for r in reports]
    for model, col in ((AccessLog, AccessLog.report_id), (AccessRequest, AccessRequest.report_id)):
        for row in session.exec(select(model).where(col.in_(rep_ids))).all():
            session.delete(row)
    for r in reports:
        Path(r.path).unlink(missing_ok=True)
        session.delete(r)
    for h in session.exec(select(Hotspot).where(Hotspot.survey_id.in_(ids))).all():
        session.delete(h)
    if first is not None:
        mobiles = [m.mobile for m in (session.get(Farmer, session.get(Farm, f["farm_id"]).farmer_id) for f in SIM_FARMS) if m]
        for m in session.exec(
            select(SmsMessage).where(SmsMessage.to_mobile.in_(mobiles), SmsMessage.kind == "NOTIFY", SmsMessage.at >= first)
        ).all():
            session.delete(m)
    for s in surveys:
        session.delete(s)
    session.commit()
    for i in ids:
        shutil.rmtree(RUNS / i, ignore_errors=True)
    return {"reset": True}
