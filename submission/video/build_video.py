"""Builds the Round 1 idea video (muted, timed for a voice-over).

    python -m submission.video.build_video

Each scene is designed as HTML at 1920x1080 (Montserrat + Inter, VoyageHack palette), rendered with
headless Edge/Chrome, and joined with short crossfades. Each scene lasts as long as its spoken line at
a calm pace (about 2.5 words a second) plus a lead-in and a pause. Writes:
  submission/video/Paradox_idea_video.mp4   the muted video
  submission/video/timing.json              when each line starts and ends (used by the voice-over studio)
  submission/video/VOICEOVER.md             the script with timings
Dashboard frames in shots/ come from the recorded run published on the live site.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SCENES = HERE / "scenes"
SHOTS = HERE / "shots"
TEAM = os.environ.get("PARADOX_TEAM", "Team BTYECODE")  # shown on screen, exactly as registered
TEAM_SAY = os.environ.get("PARADOX_TEAM_SAY", "Team Byte Code")  # how it is spoken
XF = 0.5  # crossfade seconds
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "/usr/bin/google-chrome", "/usr/bin/chromium"]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800;900&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=block');
:root{--navy:#0B2350;--blue:#226ECA;--blue2:#1C4D91;--sky:#EAF2FC;--yellow:#FDD649;--ink:#0F1B2D;--text:#33415A;--muted:#6B7A93;--line:#E1E8F3;--green:#1E8A5A;--red:#D93A3A}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1920px;height:1080px;overflow:hidden}
body{font-family:Inter,sans-serif;color:var(--text);background:#F6F9FD;position:relative}
.pad{position:absolute;inset:0;padding:110px 140px 130px;display:flex;flex-direction:column;justify-content:center}
.eyebrow{font:700 24px Montserrat;letter-spacing:3px;text-transform:uppercase;color:var(--blue)}
.h{font:800 76px/1.08 Montserrat;color:var(--ink);letter-spacing:-1.5px}
.h2{font:700 40px/1.25 Montserrat;color:var(--ink)}
.hl{background:linear-gradient(transparent 60%,var(--yellow) 60%);padding:0 8px}
.card{background:#fff;border:1px solid var(--line);border-radius:28px;box-shadow:0 18px 50px rgba(11,35,80,.08)}
.mono{font-family:'JetBrains Mono',monospace}
.chip{display:inline-block;border-radius:999px;padding:10px 22px;font:600 26px Inter}
.foot{position:absolute;left:140px;right:140px;bottom:56px;display:flex;justify-content:space-between;font:600 20px Montserrat;color:#9AA6BA;letter-spacing:1px}
.foot b{color:var(--blue)}
.shot{position:absolute;border-radius:22px;overflow:hidden;box-shadow:0 30px 80px rgba(11,35,80,.22);border:1px solid var(--line);background:#fff}
.shot img{display:block;width:100%}
.tag{position:absolute;background:var(--navy);color:#fff;border-radius:18px;padding:22px 30px;font:600 30px/1.3 Montserrat;box-shadow:0 18px 40px rgba(11,35,80,.3)}
.tag em{font-style:normal;color:var(--yellow)}
"""


def page(body: str, foot: str | None = None, bg: str = "#F6F9FD") -> str:
    f = f'<div class="foot"><span>PARADOX</span><span>{foot}</span></div>' if foot else ""
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body style='background:{bg}'>{body}{f}</body></html>"


def shot(name: str, left: int, top: int, width: int, crop_h: int, offset: int = 0, x0: int = 280, x1: int = 1640) -> str:
    """A dashboard frame in a browser-like card, cropped to the content column (x0..x1, offset..offset+crop_h, shot pixels)."""
    s = width / (x1 - x0)
    uri = (SHOTS / f"{name}.png").as_uri()
    return (f'<div class="shot" style="left:{left}px;top:{top}px;width:{width}px;height:{int(crop_h * s) + 44}px">'
            f'<div style="height:44px;background:#EEF3FA;display:flex;gap:9px;align-items:center;padding:0 18px">'
            f'<i style="width:13px;height:13px;border-radius:50%;background:#F26B5B"></i><i style="width:13px;height:13px;border-radius:50%;background:#F7C04A"></i>'
            f'<i style="width:13px;height:13px;border-radius:50%;background:#4CC26B"></i>'
            f'<span style="margin-left:18px;font:500 17px Inter;color:#7B879B">Paradox control room</span></div>'
            f'<img src="{uri}" style="width:{int(1920 * s)}px;max-width:none;margin-left:{-int(x0 * s)}px;margin-top:{-int(offset * s)}px"></div>')


def scenes() -> list[tuple[str, str, str, str]]:
    """(name, step label, spoken line, html)"""
    S = []
    add = lambda name, step, line, html: S.append((name, step, line, html))

    add("cover", "Title",
        f"Hi, we're {TEAM_SAY}, and this is Paradox, our idea for the security track of VoyageHack.",
        page(f"""<div class="pad" style="justify-content:flex-start;background:linear-gradient(135deg,#2A78D6 0%,#226ECA 45%,#1C4D91 100%)">
  <div style="position:absolute;right:-150px;top:-150px;width:540px;height:540px;border-radius:50%;background:var(--yellow)"></div>
  <div style="position:absolute;right:260px;bottom:-80px;width:160px;height:160px;border-radius:50%;background:#fff"></div>
  <div class="eyebrow" style="color:#CFE0F7">VoyageHack 4.0 &nbsp;·&nbsp; Fraud Prevention &amp; Security</div>
  <div style="margin-top:220px;font:900 210px/0.9 Montserrat;letter-spacing:-6px;color:#fff">Paradox</div>
  <div style="margin-top:46px;font:600 52px/1.2 Montserrat;color:#fff">Agentic real-time security testing for B2B travel</div>
  <div style="position:absolute;left:140px;bottom:70px;font:600 26px Inter;color:#DCE8F8">{TEAM}</div></div>"""))

    cards = [("Refund paid twice", "Cancel a booking that is already cancelled", "+₹7,776 to the wallet"),
             ("Fare set by the client", "Send your own total with the booking", "₹1 for a ₹20,000 stay"),
             ("Agency A reads agency B", "Ask for someone else's booking id", "Passports in the reply")]
    add("problem", "The problem",
        "Here's the thing about B2B travel. The bugs that cost real money don't look like bugs. A refund that pays out twice? "
        "The server says two hundred, OK. Same with a fare the agent sets themselves, or one agency reading another agency's passports.",
        page(f"""<div class="pad"><div class="eyebrow">The problem</div>
  <div class="h" style="margin-top:26px">Every one of these requests<br>returns <span class="hl">200&nbsp;OK</span>.</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:36px;margin-top:84px">
  {''.join(f'''<div class="card" style="padding:44px 42px">
    <div class="mono" style="display:inline-block;background:#E6F4EC;color:var(--green);font-size:24px;font-weight:700;border-radius:10px;padding:6px 14px">HTTP 200</div>
    <div class="h2" style="margin-top:28px">{t}</div><div style="font:500 26px/1.45 Inter;margin-top:14px;color:var(--muted)">{d}</div>
    <div style="margin-top:34px;padding-top:26px;border-top:1px solid var(--line);font:700 30px Montserrat;color:var(--red)">{r}</div></div>''' for t, d, r in cards)}
  </div></div>""", "WHY SCANNERS MISS THEM"))

    add("shift", "The idea",
        "Scanners look for bad inputs. We look for outcomes that should be impossible.",
        page("""<div class="pad" style="display:flex;flex-direction:column;justify-content:center">
  <div style="font:700 64px Montserrat;color:#A5B1C4">Scanners look for bad inputs.</div>
  <div style="font:800 104px/1.1 Montserrat;color:var(--ink);margin-top:40px;letter-spacing:-2px">Paradox looks for<br><span style="background:var(--yellow);padding:0 18px;border-radius:12px">impossible outcomes.</span></div>
  </div>""", "THE IDEA"))

    ins = ["Staging URL", "Test accounts at two agencies", "Recorded traffic (HAR)", "120 days of gateway logs", "Deploy events"]
    outs = ["Every route, including undocumented ones", "Real user journeys, step by step", "Which response value feeds which request",
            "Who owns each object", "Where the money is: the wallet, found by experiment"]
    add("learn", "1 · Learn",
        "Paradox starts with just what TBO gives us: a staging link, a few test accounts, some recorded traffic and logs. No API docs. "
        "From that, it works out the routes, how people actually book, who owns what, and where the money sits.",
        page(f"""<div class="pad"><div class="eyebrow">Step 1 · Learn the platform</div>
  <div class="h" style="margin-top:26px;font-size:66px">Only what TBO gives teams. <span style="color:#A5B1C4;text-decoration:line-through;text-decoration-thickness:5px">No API docs.</span></div>
  <div style="display:grid;grid-template-columns:1fr 120px 1.35fr;align-items:center;margin-top:70px">
   <div class="card" style="padding:40px 44px">{''.join(f'<div style="font:600 30px Inter;color:var(--ink);padding:15px 0;border-bottom:1px solid var(--line)">{x}</div>' for x in ins)}</div>
   <div style="text-align:center;font:800 90px Montserrat;color:var(--blue)">→</div>
   <div class="card" style="padding:40px 44px;background:var(--navy);border:0">{''.join(f'<div style="font:600 30px Inter;color:#fff;padding:15px 0;border-bottom:1px solid rgba(255,255,255,.12)"><span style="color:var(--yellow);margin-right:16px">✓</span>{x}</div>' for x in outs)}</div>
  </div></div>""", "LEARNED IN UNDER 2 SECONDS"))

    ops = ["Repeat a cancel", "Skip the payment", "Set the fare in the request", "Swap the agency", "Drop the session",
           "Cancel a discounted booking", "Reuse a one-time promo", "Send role or tenant fields"]
    add("mutate", "2 · Mutate",
        "Then it plays with those journeys the way a sneaky user would. Cancel twice. Skip the payment. Set your own fare. Pretend to be another agency.",
        page(f"""<div class="pad"><div class="eyebrow">Step 2 · Change real journeys</div>
  <div class="h" style="margin-top:26px">Real user journeys,<br>bent the way an attacker would.</div>
  <div style="display:flex;gap:16px;margin-top:60px;align-items:center">
   {''.join(f'<div class="card" style="padding:22px 28px;font:700 28px Montserrat;color:var(--ink)">{s}</div><div style="font:800 34px Montserrat;color:#B8C4D6">→</div>' for s in ["Search", "Quote", "Book", "Pay"])}
   <div class="card" style="padding:22px 28px;font:700 28px Montserrat;color:var(--navy);background:var(--yellow);border:0">Cancel ×2</div></div>
  <div style="display:flex;flex-wrap:wrap;gap:18px;margin-top:64px">
   {''.join(f'<span class="chip" style="background:#fff;border:2px solid var(--blue);color:var(--blue2);font-size:30px;padding:14px 28px">{o}</span>' for o in ops)}</div>
  </div>""", "16 MUTATION OPERATORS"))

    laws = [("Money", "An agency's wallet never ends its own sequence richer."),
            ("Money", "The same booking never costs less than the platform's price."),
            ("Isolation", "One agency's data never reaches another agency."),
            ("Authority", "A lower role cannot do what only a higher role does.")]
    add("laws", "3 · Check the laws",
        "After each try, it checks twelve simple rules. Your wallet can't end up richer. The same booking can't get cheaper. "
        "One agency never sees another's data. If a rule breaks, that's a finding. If not, it stays quiet.",
        page(f"""<div class="pad"><div class="eyebrow">Step 3 · Check twelve invariants</div>
  <div class="h" style="margin-top:26px">A finding exists only when<br>a <span class="hl">law breaks</span>.</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:66px">
  {''.join(f'<div class="card" style="padding:36px 42px;display:flex;gap:30px;align-items:center"><div style="font:900 64px Montserrat;color:var(--blue);min-width:70px">{i+1}</div><div><div style="font:700 22px Montserrat;letter-spacing:2px;text-transform:uppercase;color:var(--blue)">{c}</div><div style="font:600 33px/1.3 Inter;color:var(--ink);margin-top:8px">{t}</div></div></div>' for i, (c, t) in enumerate(laws))}
  </div><div style="font:500 28px Inter;color:var(--muted);margin-top:40px">+ 8 more across money, isolation, authority and data exposure</div></div>""", "12 INVARIANTS"))

    add("proof", "Proof",
        "Like this one. Cancel a booking that's already cancelled, and the wallet gains seven thousand seven hundred and seventy-six rupees. "
        "Every single time. Paradox ran it three times to be sure, and cut it down to just four requests.",
        page(shot("baseline", 140, 70, 1640, 690, 196) +
             '<div class="tag" style="right:90px;bottom:48px"><em>3 of 3</em> fresh reproductions · minimised to <em>4 requests</em></div>'))

    add("canary", "Canary data",
        "Every booking it creates carries fake details: a made-up name, email and passport. "
        "If those turn up in another agency's account, the leak proves itself.",
        page("""<div class="pad"><div class="eyebrow">Proof without guessing</div>
  <div class="h" style="margin-top:26px">Planted canaries prove every leak.</div>
  <div style="display:grid;grid-template-columns:1fr 130px 1fr;align-items:center;margin-top:76px">
   <div class="card" style="padding:44px">
    <div style="font:700 24px Montserrat;color:var(--blue);letter-spacing:2px">AGENCY A · BOOKING PARADOX CREATED</div>
    <div class="mono" style="font-size:31px;line-height:2.05;color:var(--ink);margin-top:20px">name&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b style="background:var(--yellow);padding:2px 10px;border-radius:6px">Pdx K7q2mx</b><br>email&nbsp;&nbsp;&nbsp;&nbsp;<b style="background:var(--yellow);padding:2px 10px;border-radius:6px">pdx.k7q2mx@canary.test</b><br>passport&nbsp;<b style="background:var(--yellow);padding:2px 10px;border-radius:6px">Z48271935</b></div></div>
   <div style="text-align:center;font:800 90px Montserrat;color:var(--blue)">→</div>
   <div class="card" style="padding:44px;background:var(--navy);border:0">
    <div style="font:700 24px Montserrat;color:#9FB6DA;letter-spacing:2px">AGENCY B · RESPONSE</div>
    <div class="mono" style="font-size:29px;line-height:1.9;color:#CFDBEE;margin-top:20px">{ "id": "WB10412",<br>&nbsp;&nbsp;"lead": "<b style="color:var(--navy);background:var(--yellow);padding:2px 8px;border-radius:6px">Pdx K7q2mx</b>",<br>&nbsp;&nbsp;"passport": "<b style="color:var(--navy);background:var(--yellow);padding:2px 8px;border-radius:6px">Z48271935</b>" }</div>
    <div style="font:700 32px Montserrat;color:var(--yellow);margin-top:26px">Leak proven by the canary itself</div></div>
  </div></div>""", "ISOLATION · EXPOSURE"))

    add("ticket", "Ticket",
        "Each finding turns into a ticket for the team that owns that code, with what it costs in rupees, the exact steps, and how to fix it.",
        page('<div style="position:absolute;left:140px;top:0;bottom:0;width:760px;display:flex;flex-direction:column;justify-content:center">'
             '<div class="eyebrow">Ready for the owning team</div><div class="h" style="margin-top:24px;font-size:70px">One ticket<br>per finding.</div>'
             + ''.join(f'<div style="font:600 32px Inter;color:var(--ink);padding:18px 0;border-bottom:1px solid var(--line)"><span style="color:var(--blue);margin-right:16px">●</span>{t}</div>'
                       for t in ["Rupee impact and severity", "Owner from the asset map", "Minimal proof, balance after each step", "Ready curl reproduction", "Suggested fix and retest history"])
             + '</div>' + shot("ticket", 980, 50, 800, 930, 0, 1008, 1920)))

    add("deploy", "After a deploy",
        "And it keeps watching. When a new release went out, Paradox tested the changed part first. "
        "The new amend feature trusted whatever total the client sent. It was flagged as critical about twelve seconds later.",
        page(shot("amend", 140, 80, 1640, 490, 196) +
             '<div class="tag" style="left:140px;bottom:90px">Deploy <em>v3.1</em> · bundle diff → new route tested first</div>'
             '<div class="tag" style="right:140px;bottom:90px;background:var(--yellow);color:var(--navy)">Verified <b>11.5 s</b> after the change</div>'))

    add("fixed", "Retest",
        "Once the fix shipped, Paradox re-ran its proofs, and the fixed tickets closed on their own.",
        page(shot("fixed", 310, 90, 1300, 830, 180) +
             '<div class="tag" style="right:110px;top:60px">Hotfix <em>v3.1.1</em> · retest closes only what is really fixed</div>'))

    add("inventory", "API inventory",
        "Along the way, it maps every endpoint, even an old version one route nobody remembered, which was still leaking passports.",
        page(shot("inventory", 140, 80, 1640, 600, 0) +
             '<div class="tag" style="left:140px;bottom:60px">Active · <em>zombie</em> · <em>shadow</em> · retired · new &nbsp;+&nbsp; a generated OpenAPI spec</div>'))

    add("results", "Results",
        "Does it work? We planted a hundred and seventy-two random bugs. Paradox found all of them, with zero false alarms. "
        "A regular scanner found about thirty percent.",
        page("""<div class="pad"><div class="eyebrow">Measured on 172 randomly injected defects · 22 runs</div>
  <div class="h" style="margin-top:26px">It already works.</div>
  <div style="margin-top:80px;display:grid;grid-template-columns:330px 1fr 280px;row-gap:56px;align-items:center">
   <div style="font:800 40px Montserrat;color:var(--ink)">Paradox</div>
   <div style="height:84px;border-radius:16px;background:var(--blue)"></div>
   <div style="font:800 64px Montserrat;color:var(--blue);text-align:right">172/172</div>
   <div style="font:700 36px Montserrat;color:var(--muted)">Signature scanner</div>
   <div style="height:84px"><div style="height:100%;width:29.7%;border-radius:16px;background:#B8C4D6"></div></div>
   <div style="font:800 64px Montserrat;color:#9AA6BA;text-align:right">51/172</div></div>
  <div style="display:flex;gap:30px;margin-top:80px">
   <div class="card" style="padding:28px 40px;font:600 30px Inter;color:var(--ink)">False positives: <b style="color:var(--green)">0</b> vs <b style="color:var(--red)">66</b></div>
   <div class="card" style="padding:28px 40px;font:600 30px Inter;color:var(--ink)">Money &amp; isolation bugs found by the scanner: <b style="color:var(--red)">0</b></div></div>
  </div>""", "REPRODUCIBLE · python -m bench.bench"))

    add("holdout", "Holdout",
        "We also tried it on an airline platform it had never seen. After two small, general fixes, it caught all seven planted bugs, "
        "and stayed silent on the clean version.",
        page("""<div class="pad"><div class="eyebrow">Holdout · SkyLane Air B2B, written after the agent</div>
  <div class="h" style="margin-top:26px">A platform it had never seen.</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:34px;margin-top:76px">
   <div class="card" style="padding:44px"><div style="font:900 110px Montserrat;color:var(--muted)">5/7</div><div style="font:600 30px Inter;color:var(--ink);margin-top:10px">first contact,<br>agent unchanged</div></div>
   <div class="card" style="padding:44px;background:var(--navy);border:0"><div style="font:900 110px Montserrat;color:var(--yellow)">7/7</div><div style="font:600 30px Inter;color:#fff;margin-top:10px">after two general fixes<br>(neither names the airline)</div></div>
   <div class="card" style="padding:44px"><div style="font:900 110px Montserrat;color:var(--green)">0</div><div style="font:600 30px Inter;color:var(--ink);margin-top:10px">findings on the<br>clean build</div></div></div>
  <div style="font:500 28px/1.5 Inter;color:var(--muted);margin-top:50px">Flights instead of hotels · <span class="mono">X-Session</span> instead of Bearer · PNR codes as ids · ON_HOLD → TICKETED → VOIDED · a credit line instead of a wallet</div>
  </div>""", "GENERALISES"))

    safe = [("Scope allowlist", "Any other host is refused and logged"), ("Own objects only", "Changes only what it created"),
            ("Rate cap + back-off", "Slows down on latency or errors"), ("Kill switch", "Stops before the next request"),
            ("Audit log", "Every request, replayable"), ("Human queue", "Policy questions go to a person")]
    add("safety", "Safety",
        "And it's careful. It stays in scope, only touches its own test bookings, slows down if the server struggles, "
        "has a kill switch, and logs every request.",
        page(f"""<div class="pad"><div class="eyebrow">Safety, enforced in code</div>
  <div class="h" style="margin-top:26px">Aggressive on logic. Gentle on staging.</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:30px;margin-top:70px">
  {''.join(f'<div class="card" style="padding:40px 42px"><div style="width:54px;height:8px;border-radius:4px;background:var(--yellow)"></div><div class="h2" style="margin-top:24px">{t}</div><div style="font:500 27px/1.4 Inter;color:var(--muted);margin-top:10px">{d}</div></div>' for t, d in safe)}
  </div></div>""", "COVERED BY TESTS"))

    add("close", "Close",
        "That's Paradox. It catches the bug that makes money appear, before someone else does. Thank you.",
        page(f"""<div class="pad" style="justify-content:flex-start;background:var(--navy)">
  <div style="position:absolute;right:-150px;bottom:-150px;width:540px;height:540px;border-radius:50%;background:var(--yellow)"></div>
  <div class="eyebrow" style="color:#9FB6DA">VoyageHack 4.0 · {TEAM}</div>
  <div style="margin-top:200px;font:900 170px/0.9 Montserrat;letter-spacing:-5px;color:#fff">Paradox</div>
  <div style="margin-top:44px;font:700 56px/1.2 Montserrat;color:#fff">Catch the bug that makes money appear,<br><span style="color:var(--yellow)">before someone else does.</span></div>
  <div style="position:absolute;left:140px;bottom:80px;font:500 28px Inter;color:#C5D3EA;line-height:1.6">harsh07032004.github.io/paradox &nbsp;·&nbsp; github.com/harsh07032004/paradox</div>
  </div>""", bg="#0B2350"))
    return S


def seconds(line: str) -> float:
    return round(max(4.5, len(line.split()) / 2.5 + 2.2), 1)


def render(html_path: Path, png: Path) -> None:
    exe = next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("msedge") or shutil.which("chrome")
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    "--allow-file-access-from-files", "--window-size=1920,1080", "--virtual-time-budget=10000",
                    f"--screenshot={png}", html_path.as_uri()], check=True, capture_output=True, timeout=120)


def build() -> None:
    SCENES.mkdir(exist_ok=True)
    sc = scenes()
    durs = [seconds(line) for _, _, line, _ in sc]
    pngs = []
    for i, (name, _, _, html) in enumerate(sc):
        hp, png = SCENES / f"{i:02d}_{name}.html", SCENES / f"{i:02d}_{name}.png"
        hp.write_text(html, encoding="utf-8")
        render(hp, png)
        pngs.append(png)
        print("scene", i, name, durs[i], "s")
    # clips overlap by XF for the crossfade, so each clip is extended by XF (except the last)
    args = ["ffmpeg", "-y", "-loglevel", "error"]
    for i, p in enumerate(pngs):
        args += ["-loop", "1", "-framerate", "30", "-t", str(durs[i] + (XF if i < len(pngs) - 1 else 0)), "-i", str(p)]
    chain, last, t = [], "[0:v]", 0.0
    for i in range(1, len(pngs)):
        t += durs[i - 1]
        out = f"[x{i}]"
        chain.append(f"{last}[{i}:v]xfade=transition=fade:duration={XF}:offset={t:.2f}{out}")
        last = out
    chain.append(f"{last}fade=t=in:st=0:d=0.6,fade=t=out:st={sum(durs) - 0.8:.2f}:d=0.8,format=yuv420p[v]")
    out = HERE / "Paradox_idea_video.mp4"
    subprocess.run(args + ["-filter_complex", ";".join(chain), "-map", "[v]", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                           "-r", "30", "-movflags", "+faststart", str(out)], check=True)
    # timing: the line for scene i is read while scene i is on screen
    timing, at = [], 0.0
    for (name, step, line, _), d in zip(sc, durs):
        timing.append({"start": round(at, 2), "end": round(at + d, 2), "step": step, "line": line})
        at += d
    (HERE / "timing.json").write_text(json.dumps(timing, indent=1, ensure_ascii=False), encoding="utf-8")
    mm = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"
    rows = [f"| {mm(r['start'])} to {mm(r['end'])} | {r['step']} | {r['line']} |" for r in timing]
    (HERE / "VOICEOVER.md").write_text("\n".join([
        f"# Idea video: voice-over script ({mm(at)})", "",
        "Read each line while its scene is on screen, at a calm pace. There is a short pause after every line and the video moves on by itself.",
        "Record with the voice-over studio page, or read along with `Paradox_idea_video.mp4`. "
        "`python -m submission.video.build_video` rebuilds the video and these timings.", "",
        "| Time | Scene | Say |", "|---|---|---|", *rows, ""]), encoding="utf-8")
    print("saved", out, "length", round(at, 1), "s")


if __name__ == "__main__":
    build()
