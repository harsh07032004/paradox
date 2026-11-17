"""Scores voice-over takes and finds where each scripted line is spoken.

    python -m submission.video.align_voice take1.webm [take2.webm ...]

For every take it writes <take>.aligned.json next to the audio with, per line, when the speaker starts and
finishes it and what was heard, plus a summary: share of script words heard, clipping, speech level,
background noise, and speaking rate. Uses faster-whisper (small, CPU).
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

HERE = Path(__file__).resolve().parent
LINES = [t["line"] for t in json.loads((HERE / "timing.json").read_text(encoding="utf-8"))]
norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
script, owner = [], []
for i, line in enumerate(LINES):
    for w in line.split():
        if norm(w):
            script.append(norm(w))
            owner.append(i)


def load(src: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(src), "-ar", "16000", "-ac", "1", "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def align(model: WhisperModel, src: Path) -> dict:
    audio = load(src)
    segs, _ = model.transcribe(audio, language="en", beam_size=5, word_timestamps=True, vad_filter=True,
                               condition_on_previous_text=False, initial_prompt="Paradox, VoyageHack, TBO, B2B, Byte Code, rupees.")
    heard = [(norm(w.word), float(w.start), float(w.end), w.word.strip()) for s in segs for w in s.words if norm(w.word)]
    sm = difflib.SequenceMatcher(None, script, [h[0] for h in heard], autojunk=False)
    hit = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            hit[a + k] = b + k
    out, prev = [], -1
    per = [[k for k, o in enumerate(owner) if o == i and k in hit] for i in range(len(LINES))]
    for i, idx in enumerate(per):
        if not idx:
            out.append({"line": i, "start": None, "end": None, "matched": 0, "of": owner.count(i), "heard": ""})
            continue
        h0, h1 = hit[idx[0]], hit[idx[-1]]
        nxt = next((hit[per[j][0]] for j in range(i + 1, len(per)) if per[j]), len(heard))
        while h0 - 1 > prev and heard[h0][1] - heard[h0 - 1][2] < 0.7:
            h0 -= 1
        while h1 + 1 < nxt and heard[h1 + 1][1] - heard[h1][2] < 0.9:
            h1 += 1
        prev = h1
        out.append({"line": i, "start": round(heard[h0][1], 2), "end": round(heard[h1][2], 2), "matched": len(idx),
                    "of": owner.count(i), "heard": " ".join(h[3] for h in heard[h0:h1 + 1])})
    # level and noise: 50 ms frames; speech = inside an aligned line, noise = outside every line
    fr = 800
    n = len(audio) // fr
    rms = np.sqrt((audio[: n * fr].reshape(n, fr) ** 2).mean(1) + 1e-12)
    t = np.arange(n) * 0.05
    inside = np.zeros(n, bool)
    for o in out:
        if o["start"] is not None:
            inside |= (t >= o["start"]) & (t <= o["end"])
    db = lambda x: round(float(20 * np.log10(x + 1e-9)), 1)
    speech_s = sum(o["end"] - o["start"] for o in out if o["start"] is not None)
    matched = sum(o["matched"] for o in out)
    summary = {"take": src.name, "match_pct": round(matched / len(script) * 100, 1),
               "lines_found": sum(1 for o in out if o["start"] is not None), "lines": len(LINES),
               "clipped_pct": round(float((np.abs(audio) > 0.98).mean() * 100), 3),
               "speech_db": db(np.median(rms[inside])) if inside.any() else None,
               "noise_db": db(np.median(rms[~inside])) if (~inside).any() else None,
               "words_per_s": round(len(script) / max(1, speech_s), 2)}
    summary["snr_db"] = round(summary["speech_db"] - summary["noise_db"], 1) if summary["speech_db"] is not None else None
    res = {"summary": summary, "lines": out}
    (src.parent / f"{src.stem}.aligned.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    m = WhisperModel("small", device="cpu", compute_type="int8")
    for f in sys.argv[1:]:
        print(json.dumps(align(m, Path(f))["summary"]), flush=True)
