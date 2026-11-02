from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from . import security as sec
from .db import RAW, get_session
from .deps import DEMO_MODE, actor, current_farmer, current_operator, require_admin
from . import simulation
from .ingest import analyze_background, notify_survey
from .models import (AccessLog, AccessRequest, Farm, Farmer, Hotspot, LoginChallenge, Operator, Report,
                     SessionToken, SmsMessage, Survey, now)
from .sms import notify_text, otp_text, provider

LAYERS = {"rgb", "ndvi", "ndre", "spectral_anomaly", "spectral_z", "rgb_anomaly", "fused_anomaly", "overlay"}
VERDICTS = {"PEST", "NOT_PEST", "OTHER"}


def _bad_code() -> HTTPException:
    return HTTPException(400, "Invalid or expired code")


# ---------------------------------------------------------------- helpers
def _issue_session(session: Session, kind: str, subject_id: str) -> dict:
    token = sec.new_token()
    exp = now() + sec.SESSION_TTL
    session.add(SessionToken(token_hash=sec.hash_token(token), subject_type=kind, subject_id=subject_id, expires_at=exp))
    session.commit()
    return {"token": token, "expires_at": exp.isoformat()}


def _hotspot_dict(h: Hotspot) -> dict:
    return {
        "id": h.hotspot_id, **h.props, "geometry": h.geometry, "verdict": h.verdict,
        "verdict_note": h.verdict_note, "verdict_by": h.verdict_by,
        "verdict_at": h.verdict_at.isoformat() if h.verdict_at else None,
    }


def _survey_payload(session: Session, survey: Survey) -> dict:
    hs = session.exec(select(Hotspot).where(Hotspot.survey_id == survey.id).order_by(Hotspot.hotspot_id)).all()
    rep = session.exec(select(Report).where(Report.survey_id == survey.id).order_by(Report.version.desc())).first()
    farm = session.get(Farm, survey.farm_id)
    return {
        "id": survey.id, "farm": {"id": farm.id, "name": farm.name, "crop": farm.crop},
        "status": survey.status, "created_at": survey.created_at.isoformat(), "data_source": survey.data_source,
        "summary": survey.summary.get("summary"), "image": survey.summary.get("image"),
        "branches": survey.summary.get("branches"), "quality": survey.summary.get("quality"),
        "model_version": survey.summary.get("model_version"), "warning": survey.summary.get("warning"),
        "synthetic_check": survey.summary.get("synthetic_check"),
        "dataset": survey.summary.get("dataset"),
        "layers": sorted(n for n in LAYERS if survey.run_dir and (Path(survey.run_dir) / f"{n}.png").exists()),
        "hotspots": [_hotspot_dict(h) for h in hs], "report_id": rep.id if rep else None,
    }


def _own_survey(session: Session, farmer: Farmer, survey_id: str) -> Survey:
    s = session.get(Survey, survey_id)
    farm = session.get(Farm, s.farm_id) if s else None
    if not s or farm.farmer_id != farmer.id:
        raise HTTPException(404, "Survey not found")
    return s


def _log(session: Session, report: Report, actor_type: str, actor_id: str, access_type: str, auth_id: str) -> None:
    session.add(AccessLog(farmer_id=report.farmer_id, report_id=report.id, actor_type=actor_type,
                          actor_id=actor_id, access_type=access_type, authorization_id=auth_id))
    session.commit()


# ---------------------------------------------------------------- farmer (digital) portal
farmer_router = APIRouter(prefix="/api/farmer", tags=["farmer"])


class LoginRequest(BaseModel):
    farmer_id: str


class LoginVerify(BaseModel):
    challenge_id: str
    otp: str


@farmer_router.post("/login/request")
def farmer_login_request(body: LoginRequest, session: Session = Depends(get_session)):
    farmer = session.get(Farmer, body.farmer_id.strip().upper())
    cid = sec.new_token()[:16]
    if farmer:
        recent = session.exec(select(LoginChallenge).where(
            LoginChallenge.farmer_id == farmer.id,
            LoginChallenge.expires_at > now() - sec.OTP_WINDOW + sec.OTP_TTL)).all()
        if len(recent) >= sec.OTP_REQUESTS_PER_WINDOW:
            raise HTTPException(429, "Too many code requests. Try again later.")
        otp = sec.new_otp()
        session.add(LoginChallenge(id=cid, farmer_id=farmer.id, otp_hash=sec.hash_otp(otp, cid),
                                   expires_at=now() + sec.OTP_TTL))
        session.commit()
        provider.send(session, farmer.mobile, otp_text(otp, "login"), "OTP")
    # Same response whether or not the farmer exists (no ID enumeration).
    return {"challenge_id": cid, "expires_in_s": int(sec.OTP_TTL.total_seconds())}


@farmer_router.post("/login/verify")
def farmer_login_verify(body: LoginVerify, session: Session = Depends(get_session)):
    ch = session.get(LoginChallenge, body.challenge_id)
    if not ch or ch.status != "PENDING":
        raise _bad_code()
    if sec.expired(ch.expires_at):
        ch.status = "EXPIRED"; session.add(ch); session.commit()
        raise _bad_code()
    if not sec.check_otp(body.otp.strip(), ch.id, ch.otp_hash):
        ch.attempts += 1
        if ch.attempts >= sec.OTP_MAX_ATTEMPTS:
            ch.status = "LOCKED"
        session.add(ch); session.commit()
        raise _bad_code()
    ch.status = "VERIFIED"; session.add(ch); session.commit()
    return _issue_session(session, "FARMER", ch.farmer_id)


@farmer_router.get("/me")
def farmer_me(farmer: Farmer = Depends(current_farmer), session: Session = Depends(get_session)):
    farms = session.exec(select(Farm).where(Farm.farmer_id == farmer.id)).all()
    out = []
    for f in farms:
        sv = session.exec(select(Survey).where(Survey.farm_id == f.id).order_by(Survey.created_at.desc())).all()
        out.append({"id": f.id, "name": f.name, "crop": f.crop,
                    "surveys": [{"id": s.id, "status": s.status, "created_at": s.created_at.isoformat(),
                                 "summary": s.summary.get("summary"), "data_source": s.data_source} for s in sv]})
    return {"id": farmer.id, "name": farmer.name, "village": farmer.village, "language": farmer.language, "farms": out}


@farmer_router.get("/surveys/{survey_id}")
def farmer_survey(survey_id: str, farmer: Farmer = Depends(current_farmer), session: Session = Depends(get_session)):
    return _survey_payload(session, _own_survey(session, farmer, survey_id))


@farmer_router.get("/surveys/{survey_id}/layers/{name}")
def farmer_layer(survey_id: str, name: str, farmer: Farmer = Depends(current_farmer), session: Session = Depends(get_session)):
    s = _own_survey(session, farmer, survey_id)
    p = Path(s.run_dir) / f"{name}.png"
    if name not in LAYERS or not p.exists():
        raise HTTPException(404, "Layer not available")
    return FileResponse(p, media_type="image/png")


@farmer_router.get("/surveys/{survey_id}/report")
def farmer_report(survey_id: str, download: bool = False, farmer: Farmer = Depends(current_farmer),
                  session: Session = Depends(get_session)):
    s = _own_survey(session, farmer, survey_id)
    rep = session.exec(select(Report).where(Report.survey_id == s.id).order_by(Report.version.desc())).first()
    if not rep or not Path(rep.path).exists():
        raise HTTPException(404, "Report not ready")
    _log(session, rep, "FARMER", farmer.id, "DOWNLOAD" if download else "VIEW", "SELF")
    return FileResponse(rep.path, media_type="application/pdf",
                        filename=f"{rep.id}.pdf" if download else None,
                        content_disposition_type="attachment" if download else "inline")


# ---------------------------------------------------------------- scout verdicts
verdict_router = APIRouter(prefix="/api/hotspots", tags=["verdict"])


class VerdictBody(BaseModel):
    verdict: str
    note: str = ""


@verdict_router.post("/{survey_id}/{hotspot_id}/verdict")
def set_verdict(survey_id: str, hotspot_id: str, body: VerdictBody, who: tuple[str, str] = Depends(actor),
                x_access_token: str | None = Header(None), session: Session = Depends(get_session)):
    if body.verdict not in VERDICTS:
        raise HTTPException(422, f"verdict must be one of {sorted(VERDICTS)}")
    s = session.get(Survey, survey_id)
    if not s:
        raise HTTPException(404, "Survey not found")
    farm = session.get(Farm, s.farm_id)
    kind, sid = who
    if kind == "FARMER":
        if farm.farmer_id != sid:
            raise HTTPException(404, "Survey not found")
    else:  # operators need the farmer's verified, unexpired authorization for this report
        rep = session.exec(select(Report).where(Report.survey_id == s.id).order_by(Report.version.desc())).first()
        _authorize_access(session, sid, rep.id if rep else "", x_access_token)
    h = session.exec(select(Hotspot).where(Hotspot.survey_id == survey_id, Hotspot.hotspot_id == hotspot_id)).first()
    if not h:
        raise HTTPException(404, "Hotspot not found")
    h.verdict, h.verdict_note, h.verdict_by, h.verdict_at = body.verdict, body.note[:500], f"{kind}:{sid}", now()
    session.add(h); session.commit()
    return _hotspot_dict(h)


# ---------------------------------------------------------------- assisted access (operator)
assisted_router = APIRouter(prefix="/api/assisted", tags=["assisted"])


class OperatorLogin(BaseModel):
    operator_id: str
    pin: str


class Lookup(BaseModel):
    farmer_id: str


class NewRequest(BaseModel):
    farmer_id: str
    report_id: str


class VerifyBody(BaseModel):
    otp: str


@assisted_router.post("/login")
def operator_login(body: OperatorLogin, session: Session = Depends(get_session)):
    op = session.get(Operator, body.operator_id.strip().upper())
    if not op or not sec.hmac.compare_digest(sec.hash_pin(body.pin, op.pin_salt), op.pin_hash):
        raise HTTPException(401, "Invalid operator ID or PIN")
    return {**_issue_session(session, "OPERATOR", op.id), "operator": {"id": op.id, "name": op.name, "centre": op.centre}}


@assisted_router.post("/lookup")
def lookup(body: Lookup, op: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    f = session.get(Farmer, body.farmer_id.strip().upper())
    if not f or f.access_mode not in ("ASSISTED", "BOTH"):
        raise HTTPException(404, "No assisted-access farmer found with this ID")
    reps = session.exec(select(Report).where(Report.farmer_id == f.id).order_by(Report.generated_at.desc())).all()
    out, seen = [], set()
    for r in reps:
        if r.survey_id in seen:  # newest version per survey only
            continue
        seen.add(r.survey_id)
        sv = session.get(Survey, r.survey_id)
        out.append({"report_id": r.id, "survey_id": sv.id, "generated_at": r.generated_at.isoformat(),
                    "hotspots_detected": (sv.summary.get("summary") or {}).get("hotspots_detected")})
    return {"farmer_id": f.id, "name": f.name, "village": f.village, "language": f.language,
            "masked_mobile": sec.mask_mobile(f.mobile), "reports": out}


@assisted_router.post("/requests")
def create_request(body: NewRequest, op: Operator = Depends(current_operator), session: Session = Depends(get_session)):
    f = session.get(Farmer, body.farmer_id.strip().upper())
    rep = session.get(Report, body.report_id)
    if not f or not rep or rep.farmer_id != f.id or f.access_mode not in ("ASSISTED", "BOTH"):
        raise HTTPException(404, "Report not found for this farmer")
    recent = session.exec(select(AccessRequest).where(
        AccessRequest.farmer_id == f.id, AccessRequest.created_at > now() - sec.OTP_WINDOW)).all()
    if len(recent) >= sec.OTP_REQUESTS_PER_WINDOW:
        raise HTTPException(429, "Too many code requests for this farmer. Try again later.")
    rid = sec.new_token()[:16]
    otp = sec.new_otp()
    session.add(AccessRequest(id=rid, farmer_id=f.id, report_id=rep.id, operator_id=op.id,
                              otp_hash=sec.hash_otp(otp, rid), expires_at=now() + sec.OTP_TTL))
    session.commit()
    provider.send(session, f.mobile, otp_text(otp, "assisted", op.centre), "OTP")
    return {"request_id": rid, "masked_mobile": sec.mask_mobile(f.mobile),
            "expires_in_s": int(sec.OTP_TTL.total_seconds())}


@assisted_router.post("/requests/{request_id}/verify")
def verify_request(request_id: str, body: VerifyBody, op: Operator = Depends(current_operator),
                   session: Session = Depends(get_session)):
    r = session.get(AccessRequest, request_id)
    if not r or r.operator_id != op.id or r.status != "PENDING":
        raise _bad_code()
    if sec.expired(r.expires_at):
        r.status = "EXPIRED"; session.add(r); session.commit()
        raise _bad_code()
    if not sec.check_otp(body.otp.strip(), r.id, r.otp_hash):
        r.attempts += 1
        if r.attempts >= sec.OTP_MAX_ATTEMPTS:
            r.status = "LOCKED"
        session.add(r); session.commit()
        left = max(sec.OTP_MAX_ATTEMPTS - r.attempts, 0)
        raise HTTPException(400, f"Invalid or expired code. {left} attempt(s) left." if left else "Too many attempts. Request a new code.")
    token = sec.new_token()
    r.status, r.verified_at = "VERIFIED", now()  # OTP is single-use from here on
    r.access_token_hash, r.access_expires_at = sec.hash_token(token), now() + sec.ACCESS_TTL
    session.add(r); session.commit()
    return {"access_token": token, "report_id": r.report_id, "expires_at": r.access_expires_at.isoformat()}


def _authorize_access(session: Session, operator_id: str, report_id: str, token: str | None) -> AccessRequest:
    if not token:
        raise HTTPException(401, "Farmer authorization required")
    h = sec.hash_token(token)
    r = session.exec(select(AccessRequest).where(AccessRequest.access_token_hash == h)).first()
    if (not r or r.status != "VERIFIED" or r.operator_id != operator_id or r.report_id != report_id
            or not r.access_expires_at or sec.expired(r.access_expires_at)):
        raise HTTPException(401, "Authorization missing, expired or for a different report")
    return r


@assisted_router.get("/reports/{report_id}/summary")
def assisted_summary(report_id: str, op: Operator = Depends(current_operator),
                     x_access_token: str | None = Header(None), session: Session = Depends(get_session)):
    r = _authorize_access(session, op.id, report_id, x_access_token)
    rep = session.get(Report, report_id)
    _log(session, rep, "OPERATOR", op.id, "VIEW", r.id)
    return _survey_payload(session, session.get(Survey, rep.survey_id))


@assisted_router.get("/reports/{report_id}/download")
def assisted_download(report_id: str, op: Operator = Depends(current_operator),
                      x_access_token: str | None = Header(None), session: Session = Depends(get_session)):
    r = _authorize_access(session, op.id, report_id, x_access_token)
    rep = session.get(Report, report_id)
    if not Path(rep.path).exists():
        raise HTTPException(404, "Report file missing")
    _log(session, rep, "OPERATOR", op.id, "DOWNLOAD", r.id)
    return FileResponse(rep.path, media_type="application/pdf", filename=f"{rep.id}.pdf")


# ---------------------------------------------------------------- admin
admin_router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class AnalysisBody(BaseModel):
    farm_id: str
    survey_dir: str  # path under data/raw, e.g. "synthetic/stressed"


@admin_router.post("/analyses")
def start_analysis(body: AnalysisBody, bg: BackgroundTasks, session: Session = Depends(get_session)):
    if not session.get(Farm, body.farm_id):
        raise HTTPException(404, "Unknown farm")
    d = (RAW / body.survey_dir).resolve()
    if RAW.resolve() not in d.parents or not d.is_dir():
        raise HTTPException(400, "survey_dir must be an existing folder under data/raw")
    n = len(session.exec(select(Survey).where(Survey.farm_id == body.farm_id)).all()) + 1
    sid = f"{body.farm_id}-S{n:02d}"
    session.add(Survey(id=sid, farm_id=body.farm_id, status="PROCESSING")); session.commit()
    bg.add_task(analyze_background, sid, str(d))
    return {"survey_id": sid, "status": "PROCESSING"}


@admin_router.get("/surveys/{survey_id}")
def survey_status(survey_id: str, session: Session = Depends(get_session)):
    s = session.get(Survey, survey_id)
    if not s:
        raise HTTPException(404, "Unknown survey")
    return {"id": s.id, "status": s.status, "error": s.error}


@admin_router.post("/surveys/{survey_id}/notify")
def notify(survey_id: str, session: Session = Depends(get_session)):
    s = session.get(Survey, survey_id)
    if not s or s.status != "COMPLETED":
        raise HTTPException(409, "Survey not completed")
    return notify_survey(session, s)


@admin_router.get("/sim/status")
def sim_status(session: Session = Depends(get_session)):
    return simulation.status(session)


@admin_router.post("/sim/start")
def sim_start(bg: BackgroundTasks, session: Session = Depends(get_session)):
    return simulation.start(session, bg)


@admin_router.post("/sim/reset")
def sim_reset(session: Session = Depends(get_session)):
    return simulation.reset(session)


@admin_router.get("/surveys/{survey_id}/layers/{name}")
def admin_layer(survey_id: str, name: str, session: Session = Depends(get_session)):
    s = session.get(Survey, survey_id)
    p = Path(s.run_dir) / f"{name}.png" if s and s.run_dir else None
    if name not in LAYERS or not p or not p.exists():
        raise HTTPException(404, "Layer not available")
    return FileResponse(p, media_type="image/png")


@admin_router.get("/reports/{report_id}")
def admin_report(report_id: str, download: bool = False, session: Session = Depends(get_session)):
    rep = session.get(Report, report_id)
    if not rep or not Path(rep.path).exists():
        raise HTTPException(404, "Report not found")
    _log(session, rep, "ADMIN", "admin-console", "DOWNLOAD" if download else "VIEW", "ADMIN_KEY")
    return FileResponse(rep.path, media_type="application/pdf", filename=f"{rep.id}.pdf" if download else None,
                        content_disposition_type="attachment" if download else "inline")


@admin_router.get("/overview")
def overview(session: Session = Depends(get_session)):
    rows = []
    for s in session.exec(select(Survey).order_by(Survey.created_at.desc())).all():
        farm = session.get(Farm, s.farm_id); f = session.get(Farmer, farm.farmer_id)
        sm = s.summary.get("summary") or {}
        rows.append({"survey_id": s.id, "farm": farm.name, "farmer": f.name, "farmer_id": f.id, "village": f.village,
                     "status": s.status, "hotspots": sm.get("hotspots_detected"),
                     "suspicious_percent": sm.get("suspicious_area_percent"), "data_source": s.data_source})
    logs = session.exec(select(AccessLog).order_by(AccessLog.at.desc())).all()[:25]
    return {"surveys": rows, "access_log": [l.model_dump(mode="json") for l in logs]}


# ---------------------------------------------------------------- dev: SMS outbox (demo phone simulator)
dev_router = APIRouter(prefix="/api/dev", tags=["dev"])


@dev_router.get("/sms")
def dev_sms(mobile: str, session: Session = Depends(get_session)):
    if not DEMO_MODE:
        raise HTTPException(404, "Not found")
    msgs = session.exec(select(SmsMessage).where(SmsMessage.to_mobile == mobile).order_by(SmsMessage.pk.desc())).all()[:20]
    return [m.model_dump(mode="json") for m in msgs]

