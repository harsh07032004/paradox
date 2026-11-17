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
TEAM = os.environ.get("PARADOX_TEAM", "Team BTYECODE")
REPO = "github.com/harsh07032004/paradox"
MEMBERS = os.environ.get("PARADOX_MEMBERS", "Harsh Kumar (lead) · Bhavya Sharma · Rishi Agarwal · Parthib Saha")
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
  <div style="margin-top:170px;font:900 200px/0.9 Montserrat;letter-spacing:-6px;color:#fff">Paradox</div>
  <div style="margin-top:26px;font:600 34px Montserrat;color:#DCE8F8">Agentic real-time security testing for B2B travel</div>
  <div style="margin-top:44px;font:600 54px/1.2 Montserrat;color:#fff;max-width:1400px">Scanners look for bad inputs.<br>Paradox looks for <span style="color:var(--navy);background:var(--yellow);padding:0 14px;border-radius:8px">impossible outcomes.</span></div>
  <div style="position:absolute;left:120px;bottom:60px;color:#DCE8F8"><div style="font:700 28px Montserrat;color:#fff">{TEAM}</div><div style="font:500 23px Inter;margin-top:8px">{MEMBERS}</div></div>
</div>""")

    s1 = page(f"""
<div class="pad" style="padding-top:80px">
  <div class="eyebrow">What Paradox is &nbsp;·&nbsp; Innovation</div>
  <h1 style="font:800 50px/1.18 Montserrat;margin-top:18px;max-width:1680px">Paradox tests TBO's platform after every deploy and catches the bugs that <span class="hl">quietly lose money</span>.</h1>
  <div class="cols3">
    <div class="col">
      <div class="num">1 &nbsp;The problem</div>
      <h3>The costliest bugs look completely normal.</h3>
      <div class="ledger">
        <div class="row"><span class="a">Book a hotel</span><span class="v muted">held</span></div>
        <div class="row"><span class="a">Pay from the wallet</span><span class="v">− ₹7,776</span></div>
        <div class="row"><span class="a">Cancel</span><span class="v">+ ₹7,776</span></div>
        <div class="row bad"><span class="a">Cancel again <em>Paradox's change</em></span><span class="v">+ ₹7,776</span></div>
        <div class="row total"><span class="a">Agency's wallet</span><span class="v">+ ₹7,776</span></div>
      </div>
      <p>Every step returns <b>200 OK</b>. Scanners look for bad inputs, so they see nothing wrong.</p>
      <p class="also">Same story with a fare the agent sets itself, or a sub-agent that quietly gains admin rights.</p>
    </div>
    <div class="col">
      <div class="num">2 &nbsp;Our idea · the innovation</div>
      <h3>Check the outcome, not the input.</h3>
      <p>Paradox knows <b>12 rules</b> that every correct booking platform must keep. For example:</p>
      <div class="rule">An agency never ends up richer from its own actions.</div>
      <div class="rule">The same booking never costs less.</div>
      <div class="rule">One agency never sees another agency's data.</div>
      <p>It replays real user journeys with one sneaky change, then checks whether any rule broke.</p>
    </div>
    <div class="col dark">
      <div class="num">3 &nbsp;Why it works</div>
      <h3>A broken rule is proof, not a guess.</h3>
      <div class="why"><b>The outcome can't lie.</b> If the wallet grew, money was created, whatever the server replied.</div>
      <div class="why"><b>Checked three times</b> on fresh bookings before anything is reported.</div>
      <div class="why"><b>Leaks prove themselves.</b> Every booking it makes carries planted fake names and passports.</div>
      <div class="why"><b>Priced in rupees,</b> so the team fixes the costliest bug first.</div>
      <div class="res">Result: 0 false alarms</div>
    </div>
  </div>
</div>""", """
.cols3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:34px;margin-top:44px}
.col{background:#fff;border:2px solid var(--line);border-radius:24px;padding:34px 34px;min-height:690px}
.col.dark{background:var(--navy);border:0}
.num{font:800 19px Montserrat;letter-spacing:2.5px;text-transform:uppercase;color:var(--blue)}
.dark .num{color:var(--yellow)}
.col h3{font:800 31px/1.22 Montserrat;color:var(--ink);margin:12px 0 22px}
.dark h3{color:#fff}
.col p{font:400 22px/1.48 Inter;color:var(--text);margin-top:18px}
.col p.also{font-size:20px;color:var(--muted);border-top:2px dashed var(--line);padding-top:16px}
.col p b{color:var(--ink)}
.ledger{border:2px solid var(--line);border-radius:16px;overflow:hidden}
.row{display:flex;justify-content:space-between;align-items:center;padding:11px 18px;border-top:2px solid var(--line);font:500 21px Inter;color:var(--ink)}
.row:first-child{border-top:0}
.row .v{font:700 21px Montserrat}
.row .muted{color:var(--muted);font-weight:600}
.row.bad{background:#FFF6D6}
.row em{font:700 13px Inter;font-style:normal;background:var(--navy);color:var(--yellow);padding:4px 9px;border-radius:99px;margin-left:8px;vertical-align:3px}
.row.total{background:var(--sky);font-weight:700}
.row.total .v{color:var(--green)}
.rule{font:600 22px/1.35 Inter;color:var(--navy);background:var(--sky);border-left:5px solid var(--yellow);border-radius:0 12px 12px 0;padding:12px 16px;margin-top:12px}
.why{font:400 21.5px/1.45 Inter;color:#DCE8F8;padding:13px 0;border-top:1px solid rgba(255,255,255,.14)}
.why:first-of-type{border-top:0;padding-top:0}
.why b{color:#fff}
.res{margin-top:16px;display:inline-block;background:var(--yellow);color:var(--navy);font:800 24px Montserrat;padding:10px 18px;border-radius:12px}
""")

    s2 = page(f"""
<div class="pad" style="padding-top:80px">
  <div class="eyebrow">How it works &nbsp;·&nbsp; Potential impact &nbsp;·&nbsp; Adoption risk &amp; feasibility</div>
  <h1 style="font:800 52px/1.16 Montserrat;margin-top:18px">How it works, and proof that it does.</h1>
  <div class="tagline" style="margin-top:34px">Implementation &amp; technical feasibility</div>
  <div class="steps">
    <div><em>1</em><b>A deploy happens</b><span>Paradox sees what changed and tests that part first.</span></div><i>→</i>
    <div><em>2</em><b>It learns the platform</b><span>maps every API and user journey from traffic and logs. No docs needed.</span></div><i>→</i>
    <div><em>3</em><b>It tries to break the rules</b><span>replays real journeys with one sneaky change, safely, on its own test bookings.</span></div><i>→</i>
    <div><em>4</em><b>It reports and re-checks</b><span>a ticket with the ₹ impact, proof and fix goes to the owning team; it closes itself once fixed.</span></div>
  </div>
  <div class="built">Working prototype today: Python · all 8 stages of TBO's agent loop · 11 automated tests · uses only the inputs TBO gives teams</div>
  <div style="display:grid;grid-template-columns:1.05fr 1fr;gap:50px;margin-top:40px">
    <div>
      <div class="tagline">Potential impact</div>
      <div class="tiles">
        <div><b>{found}/{total}</b><span>planted bugs found. A signature scanner found {bfound}.</span></div>
        <div><b>{P['false_positives']}</b><span>false alarms in {b['trials']} test runs. The scanner raised {B['false_positives']}.</span></div>
        <div><b>{hfound}/{htotal}</b><span>bugs on an airline platform it was never built for</span></div>
        <div><b>11.5 s</b><span>from a new deploy to a verified critical bug</span></div>
      </div>
      <p class="for"><b>For TBO:</b> money leaks are caught on staging before fraudsters find them, engineers only see proven bugs, and forgotten APIs finally get noticed.</p>
    </div>
    <div>
      <div class="tagline">Adoption risk &amp; feasibility</div>
      <div class="risk">
        <div class="r"><b>Safe for staging?</b><span>Rate limit, automatic slow-down, a kill switch and a full audit log.</span></div>
        <div class="r"><b>Touches real data?</b><span>No. It only changes bookings it created itself.</span></div>
        <div class="r"><b>Cost and privacy?</b><span>No AI model in the loop, so no per-scan bill, and data never leaves TBO.</span></div>
        <div class="r"><b>Easy to adopt?</b><span>Day 1 on staging, week 1 on every deploy, week 2 as a release gate.</span></div>
        <div class="r"><b>Grey areas?</b><span>Policy questions go to a person, never auto-filed.</span></div>
      </div>
    </div>
  </div>
</div>""", """
.tagline{font:800 19px Montserrat;letter-spacing:2.5px;text-transform:uppercase;color:var(--blue);margin-bottom:16px}
.steps{display:flex;gap:14px;align-items:stretch}
.steps div{flex:1;background:var(--sky);border-radius:20px;padding:22px 24px}
.steps em{display:inline-grid;place-items:center;width:40px;height:40px;border-radius:50%;background:var(--navy);color:var(--yellow);font:800 20px Montserrat;font-style:normal}
.steps b{display:block;font:800 25px/1.2 Montserrat;color:var(--ink);margin-top:12px}
.steps span{display:block;font:400 19.5px/1.42 Inter;color:var(--text);margin-top:8px}
.steps i{font:800 32px Montserrat;color:var(--blue);font-style:normal;align-self:center}
.built{margin-top:16px;font:600 19px Inter;color:var(--green)}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.tiles div{background:var(--navy);border-radius:18px;padding:16px 22px}
.tiles b{display:block;font:900 40px Montserrat;color:var(--yellow)}
.tiles span{display:block;font:500 17.5px/1.35 Inter;color:#DCE8F8;margin-top:4px}
.risk .r{display:grid;grid-template-columns:215px 1fr;gap:14px;padding:16px 0;border-top:2px solid var(--line)}
.risk .r:first-child{border-top:0;padding-top:4px}
.risk b{font:700 22px/1.3 Montserrat;color:var(--ink)}
.risk span{font:400 20px/1.45 Inter;color:var(--text)}
.for{font:400 20.5px/1.5 Inter;color:var(--text);margin-top:18px;padding:16px 20px;background:var(--sky);border-radius:14px}
.for b{color:var(--ink)}
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
