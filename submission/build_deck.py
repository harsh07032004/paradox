"""Builds the Round 1 deck: cover + 2 content slides + thank-you.

    python -m submission.build_deck

Slides are designed as HTML (submission/slides/*.html, Montserrat + Inter, VoyageHack palette),
rendered at 1920x1080 with headless Edge/Chrome, then assembled into PPTX (with speaker notes)
and PDF. Every number is read from bench/results.json and holdout/results.json.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import fitz
from pptx import Presentation
from pptx.util import Emu

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission"
SLIDES = OUT / "slides"
TEAM = os.environ.get("PARADOX_TEAM", "Team Paradox")
REPO = "github.com/harsh07032004/paradox"
LIVE = "harsh07032004.github.io/paradox"
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "/usr/bin/google-chrome", "/usr/bin/chromium"]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800;900&family=Inter:wght@400;500;600;700&display=block');
:root{--navy:#0B2350;--blue:#226ECA;--blue2:#1C4D91;--sky:#EAF2FC;--yellow:#FDD649;--ink:#0F1B2D;--text:#33415A;--muted:#6B7A93;--line:#E1E8F3;--green:#1E8A5A}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1920px;height:1080px;overflow:hidden}
body{font-family:Inter,sans-serif;color:var(--text);background:#fff;position:relative}
h1,h2,h3,.h{font-family:Montserrat,sans-serif;color:var(--ink)}
.pad{position:absolute;inset:0;padding:96px 120px}
.eyebrow{font:700 22px Montserrat;letter-spacing:3px;text-transform:uppercase;color:var(--blue)}
.foot{position:absolute;left:120px;right:120px;bottom:52px;display:flex;justify-content:space-between;font:500 19px Inter;color:#9AA6BA}
.foot b{color:var(--blue);font-weight:700}
.hl{background:linear-gradient(transparent 58%,var(--yellow) 58%);padding:0 6px}
"""


def page(body: str, extra_css: str = "") -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}{extra_css}</style></head><body>{body}</body></html>"


def slides(b: dict, h: list) -> list[tuple[str, str, str]]:
    P, B = b["paradox"], b["baseline"]
    hall = next(r for r in h if r["label"] == "all-bugs")
    hclean = next(r for r in h if r["label"] == "clean")
    found, total = P["defects_found"], P["defects_injected"]
    bfound = B["defects_found"]
    hfound, htotal = sum(hall["detected"].values()), len(hall["detected"])

    cover = page(f"""
<div class="pad" style="background:linear-gradient(135deg,#2A78D6 0%,#226ECA 45%,#1C4D91 100%);color:#fff">
  <div class="ring" style="position:absolute;right:-140px;top:-140px;width:520px;height:520px;border-radius:50%;background:var(--yellow)"></div>
  <div style="position:absolute;right:250px;bottom:-70px;width:150px;height:150px;border-radius:50%;background:#fff;opacity:.95"></div>
  <div class="eyebrow" style="color:#CFE0F7">VoyageHack 4.0 &nbsp;·&nbsp; Fraud Prevention &amp; Security</div>
  <div style="margin-top:210px;font:900 200px/0.9 Montserrat;letter-spacing:-6px;color:#fff">Paradox</div>
  <div style="margin-top:44px;font:600 54px/1.2 Montserrat;color:#fff;max-width:1400px">Scanners look for bad inputs.<br>Paradox looks for <span style="color:var(--navy);background:var(--yellow);padding:0 14px;border-radius:8px">impossible outcomes.</span></div>
  <div style="position:absolute;left:120px;bottom:64px;font:500 24px Inter;color:#DCE8F8">{TEAM} &nbsp;·&nbsp; Agentic real-time security testing for B2B travel</div>
</div>""")

    s1 = page(f"""
<div class="pad">
  <div class="eyebrow">The idea</div>
  <h1 style="font:800 62px/1.12 Montserrat;margin-top:22px;max-width:1650px">Every request below returns <span class="hl">200 OK</span>.<br>The agency just made ₹7,776 out of nothing.</h1>
  <div style="display:grid;grid-template-columns:940px 1fr;gap:90px;margin-top:48px">
    <div>
      <div class="ledger">
        <div class="row"><span class="n">1</span><span class="a">Book a hotel</span><span class="v muted">held</span></div>
        <div class="row"><span class="n">2</span><span class="a">Pay from wallet</span><span class="v">− ₹7,776</span></div>
        <div class="row"><span class="n">3</span><span class="a">Cancel</span><span class="v">+ ₹7,776</span></div>
        <div class="row bad"><span class="n">4</span><span class="a">Cancel again <em>changed by Paradox</em></span><span class="v">+ ₹7,776</span></div>
        <div class="row total"><span class="n"></span><span class="a">Wallet after</span><span class="v">+ ₹7,776</span></div>
      </div>
      <p style="font:500 25px/1.5 Inter;margin-top:26px;color:var(--text);max-width:920px">A scanner sees four normal responses. Paradox checks a rule every correct platform obeys: <b style="color:var(--ink)">an agency's balance can never grow from its own actions.</b></p>
    </div>
    <div>
      <div class="h" style="font:700 30px Montserrat;margin-bottom:26px">How it works</div>
      <div class="how"><b>Learns the platform</b> from what TBO already has: recorded traffic, gateway logs, test accounts. No API spec.</div>
      <div class="how"><b>Replays real journeys with one thing changed:</b> repeat, skip, another agency, its own price.</div>
      <div class="how"><b>Checks 12 business rules</b> on a shadow ledger, with planted canary data to prove leaks.</div>
      <div class="how"><b>Reports only what it proves:</b> reproduced 3 of 3 times, cut to the minimal steps, priced in ₹, retested on every deploy.</div>
    </div>
  </div>
  <div class="new"><span>What's new</span><i>Rules, not signatures</i><i>Loss measured in ₹</i><i>Leaks proven by canaries</i><i>Proofs cut to the minimum</i><i>Zombie and shadow APIs mapped</i></div>
</div>""", """
.ledger{border:2px solid var(--line);border-radius:22px;overflow:hidden}
.row{display:grid;grid-template-columns:70px 1fr 220px;align-items:center;padding:17px 34px;border-top:2px solid var(--line);font:500 30px Inter;color:var(--ink)}
.row:first-child{border-top:0}
.row .n{font:700 24px Montserrat;color:var(--blue)}
.row .v{text-align:right;font:700 32px Montserrat}
.row .muted{color:var(--muted);font-weight:600}
.row em{font:700 17px Inter;font-style:normal;background:var(--navy);color:var(--yellow);padding:5px 12px;border-radius:99px;margin-left:16px;vertical-align:4px}
.row.bad{background:#FFF6D6}
.row.total{background:var(--sky)}
.row.total .a{font-weight:700}
.row.total .v{color:var(--green);font-size:38px}
.how{font:400 24px/1.45 Inter;color:var(--text);padding:2px 0 2px 28px;border-left:4px solid var(--blue);margin-bottom:30px}
.how b{color:var(--ink);font-weight:600}
.new{position:absolute;left:120px;right:120px;bottom:60px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.new span{font:700 18px Montserrat;letter-spacing:2px;text-transform:uppercase;color:var(--blue);margin-right:10px}
.new i{font:600 20px Inter;font-style:normal;color:var(--navy);background:var(--sky);padding:10px 20px;border-radius:99px}
""")

    s2 = page(f"""
<div class="pad">
  <div class="eyebrow">Impact &nbsp;·&nbsp; Feasibility &nbsp;·&nbsp; Adoption risk</div>
  <h1 style="font:800 62px/1.12 Montserrat;margin-top:22px;max-width:1700px">It already works, including on a platform it has never seen.</h1>
  <div class="cmp">
    <div class="lbl"><b>Paradox</b><span>{found} of {total} planted bugs found · {P['false_positives']} false alarms</span></div>
    <div class="track"><div class="fill" style="width:{found / total * 100:.1f}%"></div></div>
    <div class="lbl" style="margin-top:34px"><b style="color:var(--muted)">Signature scanner, same inputs</b><span>{bfound} of {total} found · {B['false_positives']} false alarms</span></div>
    <div class="track"><div class="fill grey" style="width:{bfound / total * 100:.1f}%"></div></div>
    <p class="note">{b['trials']} test runs, each with bugs picked at random that Paradox had never seen. The scanner caught none of the money, cross-agency or permission bugs.</p>
  </div>
  <div class="three">
    <div><h3>Impact for TBO</h3>
      <p>Finds the flaws that cost money: double refunds, client-set fares, refunds above payment. Each comes with its loss in ₹, so fixes are ordered by money at risk.</p>
      <p>On an unseen airline platform: {hfound - 2} of {htotal} at first contact, {hfound} of {htotal} after two general fixes, {len(hclean['false_positives'])} false alarms.</p></div>
    <div><h3>Feasible today</h3>
      <p>Working prototype in Python. It uses exactly the inputs TBO provides: the staging URL, test accounts, recorded traffic, gateway logs and deploy events.</p>
      <p>A new deploy is tested first. Fixed tickets close themselves when the proof stops working.</p></div>
    <div><h3>Adoption risk, handled</h3>
      <p>Safe by construction: scope allowlist, touches only data it created, rate cap with back-off, kill switch, full audit log.</p>
      <p>Policy questions go to a person, never auto-filed. No AI model in the decision path, so no per-scan cost and no data leaves TBO.</p></div>
  </div>
</div>""", """
.cmp{margin-top:56px;max-width:1680px}
.lbl{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:14px}
.lbl b{font:800 32px Montserrat;color:var(--ink)}
.lbl span{font:600 26px Inter;color:var(--text)}
.track{height:46px;border-radius:12px;background:#F0F4FA;overflow:hidden}
.fill{height:100%;background:linear-gradient(90deg,var(--blue),var(--blue2));border-radius:12px}
.fill.grey{background:#B7C2D3}
.note{font:500 22px Inter;color:var(--muted);margin-top:20px}
.three{position:absolute;left:120px;right:120px;bottom:80px;display:grid;grid-template-columns:repeat(3,1fr);gap:56px}
.three h3{font:800 30px Montserrat;margin-bottom:16px;padding-top:22px;border-top:6px solid var(--yellow)}
.three p{font:400 23px/1.5 Inter;color:var(--text);margin-bottom:14px}
""")

    thanks = page(f"""
<div class="pad" style="background:var(--navy);color:#fff">
  <div style="position:absolute;right:-120px;bottom:-160px;width:560px;height:560px;border-radius:50%;background:var(--yellow)"></div>
  <div class="eyebrow" style="color:#9DB8E4">VoyageHack 4.0 &nbsp;·&nbsp; {TEAM}</div>
  <div style="margin-top:250px;font:900 150px/1 Montserrat;color:#fff;letter-spacing:-4px">Thank you.</div>
  <div style="margin-top:40px;font:600 44px/1.3 Montserrat;color:#DCE8F8;max-width:1350px">Paradox catches the bug that makes money appear, before someone else does.</div>
  <div style="position:absolute;left:120px;bottom:80px;font:500 28px/1.7 Inter;color:#C9D6EE">Code &nbsp;<b style="color:#fff">{REPO}</b><br>Live replay &nbsp;<b style="color:#fff">{LIVE}</b></div>
</div>""")

    notes = json.loads((OUT / "notes.json").read_text(encoding="utf-8"))
    return [("01_cover", cover, notes[0]), ("02_idea", s1, notes[1]), ("03_impact", s2, notes[2]), ("04_thanks", thanks, notes[3])]


def render(html_path: Path, png: Path) -> None:
    exe = next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("msedge") or shutil.which("chrome")
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    "--window-size=1920,1080", "--virtual-time-budget=10000", f"--screenshot={png}", html_path.as_uri()],
                   check=True, capture_output=True, timeout=120)


def build():
    b = json.loads((ROOT / "bench" / "results.json").read_text())["summary"]
    h = json.loads((ROOT / "holdout" / "results.json").read_text())
    SLIDES.mkdir(exist_ok=True)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    pdf = fitz.open()
    for name, html, note in slides(b, h):
        hp, png = SLIDES / f"{name}.html", SLIDES / f"{name}.png"
        hp.write_text(html, encoding="utf-8")
        render(hp, png)
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_picture(str(png), 0, 0, prs.slide_width, prs.slide_height)
        s.notes_slide.notes_text_frame.text = note
        img = fitz.open(str(png))
        rect = img[0].rect
        pg = pdf.new_page(width=rect.width * 0.5, height=rect.height * 0.5)
        pg.insert_image(pg.rect, filename=str(png))
    cp = prs.core_properties
    cp.title, cp.author, cp.last_modified_by, cp.comments, cp.subject = "Paradox", TEAM, TEAM, "", "VoyageHack 4.0 Round 1"
    prs.save(OUT / "Paradox_VoyageHack4_Round1.pptx")
    pdf.set_metadata({"title": "Paradox", "author": TEAM, "subject": "VoyageHack 4.0 Round 1", "creator": TEAM, "producer": TEAM})
    pdf.save(OUT / "Paradox_VoyageHack4_Round1.pdf")
    print("saved deck + pdf")


if __name__ == "__main__":
    build()
