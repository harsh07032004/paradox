"""Adds burned-in captions to the voiced idea video, timed word by word to the voice.

    python -m submission.video.captions

Captions use the script's own words (not the recogniser's guesses); the recogniser only supplies timing.
Spoken numbers are shown as figures (₹7,776, 172, 30%), and the team is shown as registered (BTYECODE).
Writes Paradox_idea_video_final.mp4 (captions burned in) and Paradox_idea_video.srt (separate captions file).
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess

import numpy as np
from faster_whisper import WhisperModel

from submission.video.build_video import HERE

SRC, OUT = HERE / "Paradox_idea_video_voiced.mp4", HERE / "Paradox_idea_video_final.mp4"
MAXC = 46  # characters per caption line
DISPLAY = [  # spoken words -> how they read on screen
    ("Team Byte Code", "Team BTYECODE"),
    ("seven thousand seven hundred and seventy-six rupees", "₹7,776"),
    ("a hundred and seventy-two", "172"),
    ("two hundred, OK.", "200 OK."),
    ("twelve simple rules", "12 simple rules"),
    ("thirty percent", "30%"),
    ("version one", "v1"),
    ("all seven", "all 7"),
    ("four requests", "4 requests"),
    ("three times", "3 times"),
    ("twelve seconds", "12 seconds"),
]
norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())


def words_with_times() -> list[list[dict]]:
    lines = [t["line"] for t in json.loads((HERE / "timing.json").read_text(encoding="utf-8"))]
    vt = json.loads((HERE / "voiced_timing.json").read_text(encoding="utf-8"))
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(SRC), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(audio, language="en", beam_size=5, word_timestamps=True, vad_filter=True,
                               condition_on_previous_text=False, initial_prompt="Paradox, VoyageHack, TBO, B2B, Byte Code, rupees.")
    heard = [(norm(w.word), float(w.start), float(w.end)) for s in segs for w in s.words if norm(w.word)]
    script = [(i, w) for i, line in enumerate(lines) for w in line.split()]
    sm = difflib.SequenceMatcher(None, [norm(w) for _, w in script], [h[0] for h in heard], autojunk=False)
    t = [None] * len(script)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            t[a + k] = (heard[b + k][1], heard[b + k][2])
    out = [[] for _ in lines]
    for i in range(len(lines)):
        idx = [k for k, (li, _) in enumerate(script) if li == i]
        lo, hi = vt[i]["voice_start"], vt[i]["voice_end"]
        known = [(k, t[k]) for k in idx if t[k] and lo - 0.5 <= t[k][0] <= hi + 0.5]
        for pos, k in enumerate(idx):  # fill unmatched words by interpolating between matched neighbours
            if t[k] and lo - 0.5 <= t[k][0] <= hi + 0.5:
                s, e = t[k]
            else:
                prev = max((x for x in known if x[0] < k), default=None, key=lambda x: x[0])
                nxt = min((x for x in known if x[0] > k), default=None, key=lambda x: x[0])
                p0, p1 = (prev[1][1], prev[0]) if prev else (lo, idx[0] - 1)
                n0, n1 = (nxt[1][0], nxt[0]) if nxt else (hi, idx[-1] + 1)
                f = (k - p1) / max(1, n1 - p1)
                s = p0 + f * (n0 - p0)
                e = s + 0.25
            out[i].append({"w": script[k][1], "s": s, "e": e})
    return out


def apply_display(ws: list[dict]) -> list[dict]:
    text = [w["w"] for w in ws]
    for spoken, shown in DISPLAY:
        sp = spoken.split()
        k = 0
        while k + len(sp) <= len(text):
            if [norm(x) for x in text[k:k + len(sp)]] == [norm(x) for x in sp]:
                tail = re.sub(r"^.*?([.,?!:;]*)$", r"\1", text[k + len(sp) - 1])
                merged = {"w": shown.rstrip(".,?!:;") + tail, "s": ws[k]["s"], "e": ws[k + len(sp) - 1]["e"]}
                ws = ws[:k] + [merged] + ws[k + len(sp):]
                text = [w["w"] for w in ws]
            k += 1
    return ws


def balanced(ws: list[dict]) -> list[list[dict]]:
    """Split one sentence into the fewest captions of at most MAXC characters, with even lengths."""
    n = len(" ".join(w["w"] for w in ws))
    k = max(1, -(-n // MAXC))
    while True:
        target, out, cur = n / k, [], []
        for w in ws:
            if cur and len(" ".join(x["w"] for x in cur + [w])) > target + 6 and len(out) < k - 1:
                out.append(cur)
                cur = []
            cur.append(w)
        out.append(cur)
        if all(len(" ".join(x["w"] for x in c)) <= MAXC for c in out):
            return out
        k += 1


def cues(lines: list[list[dict]]) -> list[tuple[float, float, str]]:
    out = []
    for ws in lines:
        ws = apply_display(ws)
        sent = []
        for j, w in enumerate(ws):
            sent.append(w)
            if j + 1 == len(ws) or re.search(r"[.?!:]$", w["w"]):
                for c in balanced(sent):
                    out.append([c[0]["s"] - 0.08, c[-1]["e"] + 0.3, " ".join(x["w"] for x in c)])
                sent = []
    for i in range(len(out) - 1):  # no overlaps; short gaps are bridged so captions don't flicker
        if out[i + 1][0] - out[i][1] < 0.35:
            out[i][1] = out[i + 1][0] - 0.02
        out[i][1] = max(out[i][1], out[i][0] + 0.8)
        out[i + 1][0] = max(out[i + 1][0], out[i][1] + 0.02)
    return [tuple(c) for c in out]


def stamp(t: float, ass: bool) -> str:
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}" if ass else f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"


def main() -> None:
    cs = cues(words_with_times())
    (HERE / "Paradox_idea_video.srt").write_text(
        "\n".join(f"{i + 1}\n{stamp(a, False)} --> {stamp(b, False)}\n{t}\n" for i, (a, b, t) in enumerate(cs)), encoding="utf-8")
    # navy box (#0B2350), white bold text; ASS colours are &HAABBGGRR
    ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 2", "",
           "[V4+ Styles]",
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
           "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
           "Style: Cap,Segoe UI,50,&H00FFFFFF,&H00FFFFFF,&H1050230B,&H1050230B,-1,0,0,0,100,100,0.4,0,3,16,0,2,160,160,46,1", "",
           "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    ass += [f"Dialogue: 0,{stamp(a, True)},{stamp(b, True)},Cap,,0,0,0,,{t}" for a, b, t in cs]
    (HERE / "_captions.ass").write_text("\n".join(ass) + "\n", encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", SRC.name, "-vf", "ass=_captions.ass", "-c:v", "libx264", "-preset", "slow",
                    "-crf", "20", "-c:a", "copy", "-movflags", "+faststart", OUT.name], cwd=HERE, check=True)
    (HERE / "_captions.ass").unlink()
    print("saved", OUT, len(cs), "captions")


if __name__ == "__main__":
    main()
