"""Run the ML pipeline for a survey, store results, generate the report once."""
from __future__ import annotations

import json
import traceback
from pathlib import Path

from sqlmodel import Session, select

from . import reports
from .db import MODEL_PATH, REPORTS, RUNS, engine
from .models import Farm, Farmer, Hotspot, Report, Survey, now


def ingest_run(session: Session, survey: Survey, run_dir: Path) -> Report:
    """Load a finished pipeline run into the DB and generate its report."""
    summary = json.loads((run_dir / "summary.json").read_text())
    geo = json.loads((run_dir / "hotspots.geojson").read_text())

    for old in session.exec(select(Hotspot).where(Hotspot.survey_id == survey.id)).all():
        session.delete(old)
    for f in geo["features"]:
        props = dict(f["properties"])
        session.add(Hotspot(survey_id=survey.id, hotspot_id=props["hotspot_id"], props=props, geometry=f["geometry"]))

    survey.summary = summary
    survey.run_dir = str(run_dir)
    survey.data_source = summary.get("data_source", "real")
    survey.status = "COMPLETED"
    survey.error = None
    session.add(survey)
    session.commit()
    return make_report(session, survey)


def make_report(session: Session, survey: Survey) -> Report:
    farm = session.get(Farm, survey.farm_id)
    farmer = session.get(Farmer, farm.farmer_id)
    hs = session.exec(select(Hotspot).where(Hotspot.survey_id == survey.id).order_by(Hotspot.hotspot_id)).all()
    hs_dicts = [{"props": h.props, "verdict": h.verdict} for h in hs]
    run_dir = Path(survey.run_dir)

    existing = session.exec(select(Report).where(Report.survey_id == survey.id)).all()
    version = max((r.version for r in existing), default=0) + 1
    report_id = f"RPT-{survey.id}-v{version}"
    out = REPORTS / f"{report_id}.pdf"

    map_img = reports.build_map(run_dir, survey.summary, hs_dicts)
    html = reports.build_html(survey, farmer, farm, hs_dicts, map_img, now().strftime("%d %b %Y, %H:%M UTC"))
    reports.render_pdf(html, out)

    rep = Report(id=report_id, survey_id=survey.id, farmer_id=farmer.id, version=version, path=str(out))
    session.add(rep)
    session.commit()
    return rep


def notify_survey(session: Session, survey: Survey) -> dict:
    """SMS the farmer that the survey is done (Kannada or English, crop-aware). Mock gateway in the prototype."""
    from . import security as sec
    from .sms import notify_text, provider

    farm = session.get(Farm, survey.farm_id)
    farmer = session.get(Farmer, farm.farmer_id)
    if not farmer.sms_consent:
        return {"sent": False, "reason": "no SMS consent"}
    n = (survey.summary.get("summary") or {}).get("hotspots_detected", 0)
    provider.send(session, farmer.mobile, notify_text(farmer.language, n > 0, farmer.collection_point, farmer.id, farm.crop), "NOTIFY")
    return {"sent": True, "to": sec.mask_mobile(farmer.mobile)}


def _set_stage(survey_id: str, stage: str) -> None:
    with Session(engine) as s:
        sv = s.get(Survey, survey_id)
        if sv:
            sv.stage = stage
            s.add(sv)
            s.commit()


def analyze_background(survey_id: str, survey_dir: str, model_path: Path | None = None, notify: bool = False) -> None:
    """Background job: run the pipeline, ingest it (hotspots + PDF report), optionally SMS the farmer. Never raises."""
    from agriscout_ml import pipeline

    try:
        run_dir = RUNS / survey_id
        model = model_path if model_path is not None else (MODEL_PATH if MODEL_PATH.exists() else None)
        pipeline.run(Path(survey_dir), model, run_dir, survey_id, progress=lambda st: _set_stage(survey_id, st))
        _set_stage(survey_id, "report")
        with Session(engine) as session:
            ingest_run(session, session.get(Survey, survey_id), run_dir)
            if notify:
                notify_survey(session, session.get(Survey, survey_id))
        _set_stage(survey_id, "done")
    except Exception as e:  # noqa: BLE001
        with Session(engine) as session:
            survey = session.get(Survey, survey_id)
            survey.status = "FAILED"
            survey.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
            session.add(survey)
            session.commit()
