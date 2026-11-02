"""Farm health report: one PDF per analysis, generated once and stored.

HTML is rendered to PDF by headless Chromium so Kannada text is shaped correctly
(reportlab does not do complex-script shaping).
"""
from __future__ import annotations

import base64
import html
import io
from pathlib import Path

from PIL import Image, ImageDraw

PRIORITY_COLOR = {"CRITICAL": "#b91c1c", "HIGH": "#ea580c", "MODERATE": "#ca8a04", "LOW": "#4b5563"}
VERDICT_LABEL = {None: "Pending", "PEST": "Pest damage seen", "NOT_PEST": "No pest damage", "OTHER": "Other / inconclusive"}


def _b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build_map(run_dir: Path, summary: dict, hotspots: list[dict]) -> Image.Image:
    """RGB with fused heat overlay and numbered hotspot markers."""
    rgb = Image.open(run_dir / "rgb.png").convert("RGBA")
    heat = Image.open(run_dir / "fused_anomaly.png").convert("RGBA")
    img = Image.alpha_composite(rgb, heat)
    d = ImageDraw.Draw(img)
    south, west, north, east = summary["image"]["bounds_wgs84"]
    W, H = img.size
    for i, h in enumerate(hotspots, 1):
        lon, lat = h["props"]["centroid"]
        x = (lon - west) / (east - west) * W
        y = (north - lat) / (north - south) * H
        r = max(W // 55, 9)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 235), outline=(0, 0, 0, 255), width=2)
        d.text((x - r / 2.4, y - r / 1.6), str(i), fill=(0, 0, 0, 255))
    return img.convert("RGB")


def build_html(survey, farmer, farm, hotspots: list[dict], map_img: Image.Image, generated: str) -> str:
    s = survey.summary["summary"]
    esc = html.escape
    clear = s["hotspots_detected"] == 0
    synthetic = survey.data_source == "synthetic_demo"

    rows = ""
    for i, h in enumerate(hotspots, 1):
        p = h["props"]
        rows += f"""
        <tr>
          <td><b>{i}</b> <span class="muted">{esc(p['hotspot_id'])}</span></td>
          <td><span class="chip" style="background:{PRIORITY_COLOR[p['priority']]}">{p['priority']}</span></td>
          <td>{p['estimated_area_sqm']:.0f} m² <span class="muted">({p['crop_area_percent']}%)</span></td>
          <td>{p['confidence']}</td>
          <td>{esc(p['pattern_hint'])}</td>
          <td>{esc(VERDICT_LABEL.get(h['verdict']))}</td>
        </tr>"""

    if clear:
        finding_en = "No significant anomaly was detected in this survey."
        finding_kn = "ಈ ಸಮೀಕ್ಷೆಯಲ್ಲಿ ಯಾವುದೇ ಗಮನಾರ್ಹ ಅಸಾಮಾನ್ಯತೆ ಕಂಡುಬಂದಿಲ್ಲ."
    else:
        finding_en = (
            f"{s['hotspots_detected']} area(s) covering {s['suspicious_area_percent']}% of your crop "
            f"({s['suspicious_area_sqm']:.0f} m²) look unusual and should be inspected on the ground."
        )
        finding_kn = (
            f"ನಿಮ್ಮ ಬೆಳೆಯ {s['suspicious_area_percent']}% ಭಾಗದಲ್ಲಿ ({s['hotspots_detected']} ಪ್ರದೇಶಗಳು) "
            "ಅಸಾಮಾನ್ಯತೆ ಕಂಡುಬಂದಿದೆ. ಹೊಲದಲ್ಲಿ ಪರಿಶೀಲಿಸಿ."
        )

    ds = survey.summary.get("dataset") or {}
    if synthetic:
        banner = '<div class="demo">DEMO DATA: this report was generated from a synthetic field, not a real survey.</div>'
    elif ds.get("simulated_stress"):
        banner = (
            '<div class="demo" style="background:#fffbeb;border-color:#f59e0b;color:#92400e">'
            f"REAL IMAGERY WITH SIMULATED STRESS ({esc(str(ds.get('crop', 'crop')))}, {esc(str(ds.get('license', '')))}). "
            f"{esc(str(ds.get('simulated_stress', '')))} {esc(str(ds.get('attribution', '')))}."
            "</div>"
        )
    elif ds:
        banner = (
            '<div class="demo" style="background:#eff6ff;border-color:#3b82f6;color:#1e3a8a">'
            f"REAL UAV IMAGERY FROM A PUBLIC RESEARCH DATASET ({esc(str(ds.get('crop', 'crop')))}, {esc(str(ds.get('license', '')))}). "
            f"{esc(str(ds.get('attribution', '')))}. Shown to demonstrate the pipeline; this field has no ground-verified pest or disease records."
            "</div>"
        )
    else:
        banner = ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><style>
    @page {{ size: A4; margin: 14mm; }}
    body {{ font-family: 'Segoe UI','Nirmala UI','Noto Sans Kannada',sans-serif; color:#111827; font-size:11.5px; line-height:1.45; }}
    h1 {{ font-size:22px; margin:0 0 2px; }} h2 {{ font-size:14px; margin:16px 0 6px; border-bottom:2px solid #16a34a; padding-bottom:3px; }}
    .muted {{ color:#6b7280; font-weight:400; }} .head {{ display:flex; justify-content:space-between; align-items:flex-end; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin:10px 0; }}
    .card {{ border:1px solid #d1d5db; border-radius:6px; padding:8px 10px; }} .card b {{ display:block; font-size:18px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:6px; }} th,td {{ border-bottom:1px solid #e5e7eb; padding:5px 6px; text-align:left; vertical-align:top; }}
    th {{ background:#f3f4f6; font-size:10.5px; }} .chip {{ color:#fff; border-radius:10px; padding:1px 8px; font-size:10px; font-weight:600; }}
    .map {{ display:block; max-width:100%; max-height:92mm; margin:0 auto; border:1px solid #d1d5db; border-radius:6px; }}
    h2 {{ break-after:avoid; }} tr, .warn, .card, .foot {{ break-inside:avoid; }} thead {{ display:table-header-group; }}
    .warn {{ background:#fffbeb; border:1px solid #f59e0b; border-radius:6px; padding:8px 10px; margin-top:12px; }}
    .demo {{ background:#fee2e2; border:1px solid #ef4444; color:#991b1b; padding:6px 10px; border-radius:6px; margin-bottom:8px; font-weight:600; }}
    .kn {{ font-size:13px; }} .foot {{ margin-top:14px; font-size:9.5px; color:#6b7280; }}
    </style></head><body>
    {banner}
    <div class="head"><div><h1>Crop Health Report <span class="muted kn">· ಬೆಳೆ ಆರೋಗ್ಯ ವರದಿ</span></h1>
      <div class="muted">{esc(farm.name)} · {esc(farmer.name)} · Farmer ID {esc(farmer.id)} · {esc(farmer.village)}</div></div>
      <div class="muted" style="text-align:right">Survey {esc(survey.id)}<br>{esc(generated)}</div></div>

    <h2>Summary <span class="muted kn">· ಸಾರಾಂಶ</span></h2>
    <div class="grid">
      <div class="card"><span class="muted">Valid crop area</span><b>{s['valid_crop_area_sqm']:.0f} m²</b></div>
      <div class="card"><span class="muted">Areas to inspect</span><b>{s['hotspots_detected']}</b></div>
      <div class="card"><span class="muted">Suspicious area</span><b>{s['suspicious_area_sqm']:.0f} m²</b></div>
      <div class="card"><span class="muted">Share of crop</span><b>{s['suspicious_area_percent']}%</b></div>
    </div>
    <p>{esc(finding_en)}</p>
    <p class="kn">{esc(finding_kn)}</p>

    <h2>Field map <span class="muted kn">· ಜಮೀನಿನ ನಕ್ಷೆ</span></h2>
    <img class="map" src="{_b64(map_img)}">
    <div class="muted">Numbered circles mark areas to inspect. Brighter colour means a stronger deviation from this field's normal appearance.</div>

    <h2>Areas to inspect <span class="muted kn">· ಪರಿಶೀಲಿಸಬೇಕಾದ ಪ್ರದೇಶಗಳು</span></h2>
    {"<p>None.</p>" if clear else f'<table><tr><th>#</th><th>Priority</th><th>Area</th><th>Confidence</th><th>What the pattern suggests</th><th>Ground check</th></tr>{rows}</table>'}

    <div class="warn"><b>Important.</b> {esc(survey.summary.get('warning',''))}<br>
      <span class="kn">ಇವು ಸಂಭವನೀಯ ಸಮಸ್ಯೆ ಪ್ರದೇಶಗಳು ಮಾತ್ರ. ಕೀಟ ಅಥವಾ ರೋಗವನ್ನು ಖಚಿತಪಡಿಸಲು ಹೊಲದಲ್ಲಿ ಪರಿಶೀಲನೆ ಅಗತ್ಯ.</span></div>
    <div class="foot">Priority shows how urgently to inspect, not how severe a disease is. Confidence reflects image quality, agreement between the
      image and spectral analyses, and area size; it is not a probability of damage. Model {esc(survey.summary.get('model_version',''))}.
      Kannada text is illustrative and pending review by a Kannada-speaking agricultural expert.</div>
    </body></html>"""


def render_pdf(html_str: str, out: Path) -> None:
    from playwright.sync_api import sync_playwright

    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html_str, wait_until="load")
        page.pdf(path=str(out), print_background=True, prefer_css_page_size=True)
        browser.close()
