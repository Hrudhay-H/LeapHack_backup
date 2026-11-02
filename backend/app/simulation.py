"""Survey-day simulation: three farms get a new survey from REAL imagery, one untouched and two with SIMULATED stress.

Imagery comes from `agriscout_ml.simulate` (healthy research-station site of the Thai UAV rice dataset, CC BY 4.0).
The stress patches in farms 2 and 3 are injected, not real pest damage; that is recorded in each survey's
metadata and repeated in the UI and PDF. Prepare the imagery once with:
  uv run python -m agriscout_ml.simulate data/raw/sim --train data/models/sim_rice.pt
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
    {"farm_id": "FARM-101", "farmer_id": "MDY-003", "name": "Pandavapura Paddy Plot", "dir": "sim/sim_a"},
    {"farm_id": "FARM-102", "farmer_id": "MDY-001", "name": "Kikkeri Paddy Plot B", "dir": "sim/sim_b"},
    {"farm_id": "FARM-103", "farmer_id": "MDY-002", "name": "Maddur Paddy Plot 2", "dir": "sim/sim_c"},
]
PREPARE_CMD = "uv run python -m agriscout_ml.simulate data/raw/sim --train data/models/sim_rice.pt"


def _sid(farm_id: str) -> str:
    return f"{farm_id}-S01"


def missing_inputs() -> list[str]:
    miss = [f["dir"] for f in SIM_FARMS if not (RAW / f["dir"] / "rgb.tif").exists()]
    if not SIM_MODEL_PATH.exists():
        miss.append(SIM_MODEL_PATH.name)
    return miss


def _run_all(farms: list[dict]) -> None:
    for f in farms:  # one after another: CPU-bound, and SQLite is single-writer
        analyze_background(_sid(f["farm_id"]), str(RAW / f["dir"]), model_path=SIM_MODEL_PATH, notify=True)


def start(session: Session, bg: BackgroundTasks) -> dict:
    miss = missing_inputs()
    if miss:
        raise HTTPException(409, f"Simulation imagery not prepared ({', '.join(miss)}). Run: {PREPARE_CMD}")
    ids = [f["farm_id"] for f in SIM_FARMS]
    if session.exec(select(Survey).where(Survey.farm_id.in_(ids))).first():
        raise HTTPException(409, "A simulation already exists. Reset it first.")
    for f in SIM_FARMS:
        if not session.get(Farmer, f["farmer_id"]):
            raise HTTPException(409, f"Farmer {f['farmer_id']} is missing. Run the seed first.")
        session.merge(Farm(id=f["farm_id"], farmer_id=f["farmer_id"], name=f["name"], crop="Paddy"))
    session.commit()
    for f in SIM_FARMS:
        session.add(Survey(id=_sid(f["farm_id"]), farm_id=f["farm_id"], status="PROCESSING", stage="received", data_source="pending"))
    session.commit()
    bg.add_task(_run_all, SIM_FARMS)
    return {"started": [_sid(f["farm_id"]) for f in SIM_FARMS]}


def _survey_meta(dir_: str) -> dict:
    p = RAW / dir_ / "survey.json"
    return json.loads(p.read_text()) if p.exists() else {}


def status(session: Session) -> dict:
    out = []
    for f in SIM_FARMS:
        farmer = session.get(Farmer, f["farmer_id"])
        sv = session.get(Survey, _sid(f["farm_id"]))
        planted = _survey_meta(f["dir"]).get("planted") or []
        row = {
            "farm_id": f["farm_id"],
            "farm_name": f["name"],
            "farmer_id": f["farmer_id"],
            "farmer": farmer.name if farmer else None,
            "village": farmer.village if farmer else None,
            "language": farmer.language if farmer else None,
            "access_mode": farmer.access_mode if farmer else None,
            "input": {
                "source": "Real UAV orthomosaic of a rice research station (Thai UAV rice dataset, CC BY 4.0)",
                "simulated_stress": bool(planted),
                "planted_patches": [
                    {"name": p.get("name"), "radius_m": p.get("radius_m"), "severity": p.get("severity")} for p in planted
                ],
            },
            "survey_id": sv.id if sv else None,
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
    ids = [_sid(f["farm_id"]) for f in SIM_FARMS]
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
        mobiles = [m.mobile for m in (session.get(Farmer, f["farmer_id"]) for f in SIM_FARMS) if m]
        for m in session.exec(
            select(SmsMessage).where(SmsMessage.to_mobile.in_(mobiles), SmsMessage.kind == "NOTIFY", SmsMessage.at >= first)
        ).all():
            session.delete(m)
    for s in surveys:
        session.delete(s)
    session.commit()
    for f in SIM_FARMS:  # farms go too, so dashboards return to their pre-simulation state
        farm = session.get(Farm, f["farm_id"])
        if farm:
            session.delete(farm)
    session.commit()
    for i in ids:
        shutil.rmtree(RUNS / i, ignore_errors=True)
    return {"reset": True}
