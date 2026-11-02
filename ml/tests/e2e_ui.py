"""Browser end-to-end smoke test (needs API on :8000 and web on :5173 with seeded demo data).

  uv run python ml/tests/e2e_ui.py [OUT_DIR]
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

WEB = "http://localhost:5173"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "data/e2e")
OUT.mkdir(parents=True, exist_ok=True)
results: list[tuple[str, bool, str]] = []
problems: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def latest_otp(mobile: str) -> str:
    msgs = requests.get(f"{WEB}/api/dev/sms", params={"mobile": mobile}, timeout=10).json()
    m = re.search(r"OTP (\d{6})", msgs[0]["body"])
    return m.group(1)


import atexit

def _issues():
    for pr in sorted(set(problems)):
        print('BROWSER ISSUE:', pr)


atexit.register(_issues)

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    page = ctx.new_page()
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.request.method} {r.url}") if r.status >= 400 else None)

    # ---- farmer login (Kannada farmer)
    page.goto(f"{WEB}/farmer")
    page.get_by_role("button", name="Send code to my phone").click()
    page.get_by_label("6-digit code").wait_for()
    page.get_by_label("6-digit code").fill(latest_otp("9000000001"))
    page.get_by_role("button", name="Verify and continue").click()
    page.wait_for_url("**/farmer/dashboard")
    page.locator("li", has_text="HS_001").first.wait_for(timeout=20000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / "farmer_dashboard.png"), full_page=True)
    n_cards = page.locator("li", has_text=re.compile(r"HS_\d{3}")).count()
    check("farmer dashboard shows hotspot cards", n_cards >= 1, f"{n_cards} cards")

    # ---- scroll-wheel must scroll the page, not zoom the map
    page.mouse.move(400, 500)
    y0 = page.evaluate("window.scrollY")
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(500)
    y1 = page.evaluate("window.scrollY")
    check("mouse wheel over map scrolls the page", y1 > y0, f"scrollY {y0}->{y1}")

    # ---- scout verdict persists
    first = page.locator("li", has_text="HS_001").first
    first.scroll_into_view_if_needed()
    buttons = first.locator("button")
    check("verdict has three buttons", buttons.count() == 3, f"{buttons.count()}")
    buttons.nth(0).click()  # PEST
    page.wait_for_timeout(1200)
    pest_label = first.locator("button").nth(0).inner_text()
    state = requests.get(f"{WEB}/api/farmer/surveys/FARM-001-S01", headers={"Authorization": "Bearer " + page.evaluate("sessionStorage.getItem('agri.farmer.token')")}).json()
    h1 = next(h for h in state["hotspots"] if h["id"] == "HS_001")
    check("verdict saved on the server", h1["verdict"] == "PEST", f"verdict={h1['verdict']} by={h1['verdict_by']}")
    page.reload()
    page.locator("li", has_text="HS_001").first.wait_for(timeout=20000)
    shown = page.locator("li", has_text="HS_001").first.inner_text()
    check("verdict still shown after reload", pest_label in shown and "ಕೀಟ ಹಾನಿ ಕಂಡಿದೆ" in shown.split("\n")[-4:].__str__() or "ಕೀಟ ಹಾನಿ ಕಂಡಿದೆ" in shown)

    # ---- PDF download + view
    with page.expect_download(timeout=60000) as dl:
        page.get_by_role("button", name=re.compile("ಡೌನ್‌ಲೋಡ್|Download")).click()
    pdf_path = OUT / "downloaded_report.pdf"
    dl.value.save_as(str(pdf_path))
    head = pdf_path.read_bytes()[:5]
    check("PDF download is a real PDF", head == b"%PDF-" and pdf_path.stat().st_size > 20000, f"{pdf_path.stat().st_size} bytes, filename={dl.value.suggested_filename}")

    # Headless Chromium has no PDF viewer: it turns the blob navigation into a download instead.
    viewer_downloads: list = []
    with ctx.expect_page(timeout=30000) as newp:
        page.get_by_role("button", name=re.compile("ವರದಿ ನೋಡಿ|View report")).click()
    viewer = newp.value
    viewer.on("download", lambda d: viewer_downloads.append(d))
    viewer.wait_for_timeout(3500)
    viewed = viewer.url.startswith("blob:") or bool(viewer_downloads)
    check("view-report delivers the PDF to a new tab", viewed, f"url={viewer.url[:30]} downloads={len(viewer_downloads)}")
    viewer.close()

    # ---- the verdict must appear in a freshly generated PDF? (reports are generated once, so it should NOT)
    # ---- admin: run a new analysis, then SMS, then access log
    admin = ctx.new_page()
    admin.on("response", lambda r: problems.append(f"HTTP {r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
    admin.goto(f"{WEB}/admin")
    admin.get_by_text("FARM-001-S01").first.wait_for(timeout=15000)
    admin.get_by_role("button", name="Run analysis").click()
    t0 = time.time()
    done = False
    while time.time() - t0 < 240:
        admin.wait_for_timeout(3000)
        if admin.get_by_text(re.compile(r"Analysis FARM-001-S0\d completed")).count():
            done = True
            break
        if admin.get_by_text(re.compile(r"failed")).count():
            break
    admin.screenshot(path=str(OUT / "admin_after_run.png"), full_page=True)
    check("admin: run analysis completes", done, f"{time.time() - t0:.0f}s")
    rows = admin.locator("tbody tr").filter(has_text="COMPLETED").count()
    check("admin: surveys table lists completed surveys", rows >= 3, f"{rows} completed rows")
    admin.get_by_role("button", name="Send SMS").first.click()
    admin.wait_for_timeout(1000)
    check("admin: send SMS reports queued", admin.get_by_text(re.compile("SMS queued")).count() == 1)
    sms = requests.get(f"{WEB}/api/dev/sms", params={"mobile": "9000000001"}, timeout=10).json()
    notify = [m for m in sms if m["kind"] == "NOTIFY"]
    check("Kannada notification SMS stored", bool(notify) and "ನಮಸ್ಕಾರ" in notify[0]["body"], (notify[0]["body"][:60] if notify else "none"))
    admin.get_by_role("button", name="Refresh").click()
    admin.wait_for_timeout(800)
    log_rows = admin.locator("h2:has-text('Report access log') ~ table tbody tr, h2:has-text('Report access log') + table tbody tr").count()
    check("admin: access log shows the farmer's PDF views", log_rows >= 2, f"{log_rows} log rows")

    # ---- re-open the farmer dashboard: newest survey should now be shown
    page.reload()
    page.locator("li", has_text="HS_001").first.wait_for(timeout=20000)
    page.screenshot(path=str(OUT / "farmer_after_new_survey.png"), full_page=True)
    # ---- real public-dataset maize field (farmer MDY-003, English)
    real = ctx.new_page()
    real.on("response", lambda r: problems.append(f"HTTP {r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
    real.goto(f"{WEB}/farmer")
    real.get_by_label("Farmer ID").fill("MDY-003")
    real.get_by_role("button", name="Send code to my phone").click()
    real.get_by_label("6-digit code").wait_for()
    real.get_by_label("6-digit code").fill(latest_otp("9000000003"))
    real.get_by_role("button", name="Verify and continue").click()
    real.wait_for_url("**/farmer/dashboard")
    real.get_by_text("No significant anomaly detected").first.wait_for(timeout=20000)
    check("real field: 'no significant anomaly' is shown", True)
    check("real field: public-dataset banner shown", real.get_by_text("Real UAV imagery from a public research dataset").count() == 1)
    check("real field: no demo-data (synthetic) banner", real.get_by_text("This field is synthetic").count() == 0)
    real.get_by_label("Deviation from field median").wait_for(timeout=20000)
    real.get_by_label("Deviation from field median").check()
    real.wait_for_timeout(1500)
    real.screenshot(path=str(OUT / "real_maize_dashboard.png"), full_page=True)
    check("real field: deviation layer selectable", real.get_by_label("Deviation from field median").is_checked())
    with real.expect_download(timeout=60000) as dl2:
        real.get_by_role("button", name="Download PDF").click()
    pdf2 = OUT / "real_maize_report.pdf"
    dl2.value.save_as(str(pdf2))
    import pypdfium2 as pdfium
    text = " ".join("".join(pg.get_textpage().get_text_range() for pg in pdfium.PdfDocument(str(pdf2))).split()).replace("￾", "-")
    (OUT / "real_maize_report.txt").write_text(text, encoding="utf-8")
    check("real field: PDF carries dataset banner and attribution", "PUBLIC RESEARCH DATASET" in text and "Zenodo" in text and "no ground-verified" in text, text[:160])
    check("real field: PDF says maize crop, not paddy", "Maize" in text or "maize" in text)
    rsms = requests.get(f"{WEB}/api/dev/sms", params={"mobile": "9000000003"}, timeout=10).json()
    check("real field: PDF states no significant anomaly", "No significant anomaly was detected" in text)

    # ---- survey-day simulator: three farms, real imagery, one clean and two with simulated stress
    ADMIN = {"X-Admin-Key": "demo-admin"}
    sim = ctx.new_page()
    sim.on("response", lambda r: problems.append(f"HTTP {r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
    sim.goto(f"{WEB}/admin")
    sim.get_by_role("link", name="Survey-day simulator").click()
    sim.wait_for_url("**/admin/simulate")
    sim.get_by_role("button", name="Start survey day").wait_for()
    sim.get_by_text("Simulated input").first.wait_for(timeout=15000)
    check("simulator: three farm cards listed before start", sim.get_by_text("Simulated input").count() == 3)
    sim.get_by_role("button", name="Start survey day").click()
    t1 = time.time()
    sim.get_by_text("Done. Open the reports below").wait_for(timeout=420000)
    check("simulator: all three surveys finish", True, f"{time.time() - t1:.0f}s")
    sim.wait_for_timeout(1500)
    sim.screenshot(path=str(OUT / "simulator_done.png"), full_page=True)
    st = requests.get(f"{WEB}/api/admin/sim/status", headers=ADMIN, timeout=20).json()
    res = {f["farm_id"]: f for f in st["farms"]}
    check("simulator: farm 1 (untouched real imagery) has no anomaly", res["FARM-101"]["result"]["hotspots"] == 0, str(res["FARM-101"]["result"]["hotspots"]))
    check("simulator: farm 2 has hotspots", (res["FARM-102"]["result"]["hotspots"] or 0) >= 1, str(res["FARM-102"]["result"]["hotspots"]))
    check("simulator: farm 3 has hotspots", (res["FARM-103"]["result"]["hotspots"] or 0) >= 1, str(res["FARM-103"]["result"]["hotspots"]))
    check("simulator: 'no significant anomaly' and 'flagged' wording on cards",
          sim.get_by_text("No significant anomaly detected.").count() == 1 and sim.get_by_text("flagged for ground inspection").count() == 2)
    check("simulator: self-check shown only for the two stressed farms", sim.get_by_text("Self-check against the added patches").count() == 2)
    check("simulator: SMS sent to all three farmers", all(res[k]["result"]["notified"] for k in res))
    check("simulator: keypad-phone farmer's SMS is Kannada", "ನಮಸ್ಕಾರ" in (res["FARM-103"]["result"]["sms"] or ""))
    import pypdfium2 as pdfium
    pdf_text = {}
    for fid, f in res.items():
        rid = f["result"]["report_id"]
        b = requests.get(f"{WEB}/api/admin/reports/{rid}", headers=ADMIN, timeout=60).content
        (OUT / f"{rid}.pdf").write_bytes(b)
        pdf_text[fid] = " ".join("".join(pg.get_textpage().get_text_range() for pg in pdfium.PdfDocument(str(OUT / f"{rid}.pdf"))).split())
    check("simulator: three real PDF reports", all(len(pdf_text[k]) > 300 for k in pdf_text))
    check("simulator: stressed farms' PDFs say SIMULATED STRESS, clean farm's does not",
          "SIMULATED STRESS" in pdf_text["FARM-102"] and "SIMULATED STRESS" in pdf_text["FARM-103"] and "SIMULATED STRESS" not in pdf_text["FARM-101"])
    check("simulator: clean farm's PDF states no significant anomaly", "No significant anomaly was detected" in pdf_text["FARM-101"])
    check("simulator: stressed farms' PDFs list areas to inspect", all("Areas to inspect" in pdf_text[k] and "Pattern consistent" in pdf_text[k] or "pattern" in pdf_text[k].lower() for k in ("FARM-102", "FARM-103")))

    # farmer sees the new survey first, with a survey selector
    fp = ctx.new_page()
    fp.goto(f"{WEB}/farmer")
    fp.get_by_label("Farmer ID").fill("MDY-001")
    fp.get_by_role("button", name="Send code to my phone").click()
    fp.get_by_label("6-digit code").wait_for()
    fp.get_by_label("6-digit code").fill(latest_otp("9000000001"))
    fp.get_by_role("button", name="Verify and continue").click()
    fp.wait_for_url("**/farmer/dashboard")
    fp.get_by_text("Real imagery with simulated stress.").wait_for(timeout=30000)
    check("farmer dashboard opens on the new survey with the simulated-stress banner", True)
    check("farmer dashboard has a survey selector with the old and new surveys", fp.locator("select option").count() >= 2, str(fp.locator("select option").count()))
    fp.screenshot(path=str(OUT / "farmer_new_survey.png"), full_page=True)

    # reset returns everything to the pre-simulation state
    sim.get_by_role("button", name="Reset simulation").click()
    sim.get_by_role("button", name="Start survey day").wait_for(timeout=30000)
    sim.wait_for_timeout(1500)
    st2 = requests.get(f"{WEB}/api/admin/sim/status", headers=ADMIN, timeout=20).json()
    check("simulator: reset clears all three surveys", not st2["started"] and all(f["status"] == "NOT_STARTED" for f in st2["farms"]))
    ov = requests.get(f"{WEB}/api/admin/overview", headers=ADMIN, timeout=20).json()
    check("simulator: reset removes the simulated surveys from the admin overview", not any(r["survey_id"].startswith("FARM-10") for r in ov["surveys"]))

    browser.close()

passed = sum(ok for _, ok, _ in results)
print(f"\n{passed}/{len(results)} checks passed")
seen = set(problems)
json.dump({"results": results, "issues": sorted(seen)}, open(OUT / "e2e_result.json", "w"), indent=2)
sys.exit(0 if passed == len(results) else 1)
