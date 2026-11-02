"""API flow tests against a COPY of the seeded demo DB (run `python -m backend.app.seed` first)."""
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def db_file(tmp_path_factory):
    import os

    src = ROOT / "data" / "agriscout.db"
    if not src.exists():
        pytest.skip("seed the demo DB first")
    path = tmp_path_factory.mktemp("db") / "t.db"
    os.environ["AGRISCOUT_DB"] = str(path)  # must be set before the app is imported
    return path, src


@pytest.fixture()
def client(db_file):
    path, src = db_file
    from backend.app.db import engine
    from backend.app.main import app
    from fastapi.testclient import TestClient

    engine.dispose()
    shutil.copy(src, path)  # fresh seeded state (and rate-limit counters) per test
    with TestClient(app) as c:
        yield c


def last_otp(c, mobile):
    msgs = c.get("/api/dev/sms", params={"mobile": mobile}).json()
    return re.search(r"\b(\d{6})\b", msgs[0]["body"]).group(1)


def op_login(c, op="OP-KIK", pin="1234"):
    r = c.post("/api/assisted/login", json={"operator_id": op, "pin": pin})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_farmer_login_and_survey(client):
    ch = client.post("/api/farmer/login/request", json={"farmer_id": "mdy-001"}).json()
    otp = last_otp(client, "9000000001")
    tok = client.post("/api/farmer/login/verify", json={"challenge_id": ch["challenge_id"], "otp": otp}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    me = client.get("/api/farmer/me", headers=h).json()
    sid = me["farms"][0]["surveys"][0]["id"]
    s = client.get(f"/api/farmer/surveys/{sid}", headers=h).json()
    assert s["summary"]["hotspots_detected"] == 4
    assert client.get(f"/api/farmer/surveys/{sid}/report", headers=h).headers["content-type"] == "application/pdf"
    assert client.get(f"/api/farmer/surveys/{sid}/layers/overlay", headers=h).status_code == 200
    assert client.get(f"/api/farmer/surveys/{sid}/layers/../../etc", headers=h).status_code in (404, 422)
    # another farmer's survey is not visible
    assert client.get("/api/farmer/surveys/FARM-002-S01", headers=h).status_code == 404


def test_unknown_farmer_gets_same_response_shape(client):
    r = client.post("/api/farmer/login/request", json={"farmer_id": "NOPE-1"})
    assert r.status_code == 200 and "challenge_id" in r.json()


def test_wrong_otp_locks_challenge(client):
    ch = client.post("/api/farmer/login/request", json={"farmer_id": "MDY-001"}).json()["challenge_id"]
    real = last_otp(client, "9000000001")
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(3):
        assert client.post("/api/farmer/login/verify", json={"challenge_id": ch, "otp": wrong}).status_code == 400
    # even the correct OTP no longer works once locked
    assert client.post("/api/farmer/login/verify", json={"challenge_id": ch, "otp": real}).status_code == 400


def test_assisted_flow_end_to_end(client):
    oh = op_login(client)
    lk = client.post("/api/assisted/lookup", json={"farmer_id": "MDY-002"}, headers=oh).json()
    assert "9000000002" not in str(lk) and lk["masked_mobile"].startswith("90")
    rid = lk["reports"][0]["report_id"]
    req = client.post("/api/assisted/requests", json={"farmer_id": "MDY-002", "report_id": rid}, headers=oh).json()
    # no access without the farmer's OTP
    assert client.get(f"/api/assisted/reports/{rid}/download", headers=oh).status_code == 401
    otp = last_otp(client, "9000000002")
    v = client.post(f"/api/assisted/requests/{req['request_id']}/verify", json={"otp": otp}, headers=oh)
    assert v.status_code == 200
    ah = {**oh, "X-Access-Token": v.json()["access_token"]}
    d = client.get(f"/api/assisted/reports/{rid}/download", headers=ah)
    assert d.status_code == 200 and d.headers["content-type"] == "application/pdf"
    # OTP is single-use
    again = client.post(f"/api/assisted/requests/{req['request_id']}/verify", json={"otp": otp}, headers=oh)
    assert again.status_code == 400
    # token is bound to this report and to this operator
    other = "RPT-FARM-001-S01-v1"
    assert client.get(f"/api/assisted/reports/{other}/download", headers=ah).status_code == 401
    oh2 = op_login(client, "OP-MAD")
    assert client.get(f"/api/assisted/reports/{rid}/download", headers={**oh2, "X-Access-Token": ah["X-Access-Token"]}).status_code == 401
    # access is audited
    log = client.get("/api/admin/overview", headers={"X-Admin-Key": "demo-admin"}).json()["access_log"]
    assert any(l["report_id"] == rid and l["access_type"] == "DOWNLOAD" and l["actor_type"] == "OPERATOR" for l in log)


def test_assisted_wrong_otp_attempts_then_lock(client):
    oh = op_login(client)
    lk = client.post("/api/assisted/lookup", json={"farmer_id": "MDY-001"}, headers=oh).json()
    rid = lk["reports"][0]["report_id"]
    req = client.post("/api/assisted/requests", json={"farmer_id": "MDY-001", "report_id": rid}, headers=oh).json()
    real = last_otp(client, "9000000001")
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(3):
        assert client.post(f"/api/assisted/requests/{req['request_id']}/verify", json={"otp": wrong}, headers=oh).status_code == 400
    assert client.post(f"/api/assisted/requests/{req['request_id']}/verify", json={"otp": real}, headers=oh).status_code == 400


def test_digital_only_farmer_blocked_from_assisted(client):
    oh = op_login(client)
    assert client.post("/api/assisted/lookup", json={"farmer_id": "MDY-003"}, headers=oh).status_code == 404


def test_operator_bad_pin_and_verdict_requires_authorization(client):
    assert client.post("/api/assisted/login", json={"operator_id": "OP-KIK", "pin": "9999"}).status_code == 401
    oh = op_login(client)
    r = client.post("/api/hotspots/FARM-001-S01/HS_001/verdict", json={"verdict": "PEST"}, headers=oh)
    assert r.status_code == 401  # operator has no farmer authorization for this report


def test_scout_verdict_recorded_by_farmer(client):
    ch = client.post("/api/farmer/login/request", json={"farmer_id": "MDY-001"}).json()
    tok = client.post("/api/farmer/login/verify", json={"challenge_id": ch["challenge_id"], "otp": last_otp(client, "9000000001")}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    r = client.post("/api/hotspots/FARM-001-S01/HS_001/verdict", json={"verdict": "NOT_PEST", "note": "water stress"}, headers=h)
    assert r.status_code == 200 and r.json()["verdict"] == "NOT_PEST"
    assert client.post("/api/hotspots/FARM-001-S01/HS_001/verdict", json={"verdict": "BAD"}, headers=h).status_code == 422


def test_notify_sends_kannada_sms(client):
    r = client.post("/api/admin/surveys/FARM-001-S01/notify", headers={"X-Admin-Key": "demo-admin"})
    assert r.json()["sent"] is True
    body = client.get("/api/dev/sms", params={"mobile": "9000000001"}).json()[0]["body"]
    assert "ಸಮೀಕ್ಷೆ" in body and "MDY-001" in body
    assert client.post("/api/admin/surveys/FARM-001-S01/notify").status_code == 403
