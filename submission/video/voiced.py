"""Builds the final voiced idea video from one or more recorded takes.

    python -m submission.video.align_voice takeA.webm takeB.webm      # first: find every line in every take
    python -m submission.video.voiced takeA.webm takeB.webm --pick 1,0,1,...  [--tempo 1.06]

For each scripted line it uses the take named in --pick (0 = first take given), or, without --pick, the take
whose reading of that line best matches the script. Each line is cut from its take with a little air around it,
takes are level-matched, the silences between lines are shortened to a natural beat, and the voice can be
sped up slightly without changing pitch. Every scene is then re-timed so the picture changes right after
its line ends. Writes submission/video/Paradox_idea_video_voiced.mp4 and voiced_timing.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from submission.video.build_video import HERE, SCENES, assemble

LEAD, TAIL = 0.14, 0.26   # air kept before and after each spoken line (seconds, in the original take)
GAP = 0.42                # silence between lines in the final cut
INTRO, OUTRO = 0.55, 1.6  # before the first line and after the last


def dur(f: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("takes", nargs="+")
    ap.add_argument("--pick", help="comma-separated take index per line")
    ap.add_argument("--tempo", type=float, default=1.0)
    a = ap.parse_args()
    takes = [Path(t) for t in a.takes]
    al = [json.loads((t.parent / f"{t.stem}.aligned.json").read_text(encoding="utf-8")) for t in takes]
    n = len(al[0]["lines"])
    if a.pick:
        pick = [int(x) for x in a.pick.split(",")]
    else:
        pick = [max(range(len(al)), key=lambda k: (al[k]["lines"][i]["matched"] / max(1, al[k]["lines"][i]["of"]))) for i in range(n)]
    assert len(pick) == n
    ref_db = max(x["summary"]["speech_db"] for x in al)
    tmp = HERE / "_voice"
    tmp.mkdir(exist_ok=True)
    parts, seg_len = [], []
    for i in range(n):
        k = pick[i]
        lines = al[k]["lines"]
        o = lines[i]
        prev_end = lines[i - 1]["end"] if i else 0.0
        next_start = lines[i + 1]["start"] if i + 1 < n and lines[i + 1]["start"] is not None else o["end"] + 2
        s = max(o["start"] - LEAD, (prev_end + o["start"]) / 2 if i else 0.0)
        e = min(o["end"] + TAIL, (o["end"] + next_start) / 2)
        gain = ref_db - al[k]["summary"]["speech_db"]
        f = tmp / f"l{i:02d}.wav"
        af = f"atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS,volume={gain:.2f}dB,afade=t=in:d=0.04,afade=t=out:st={e - s - 0.06:.3f}:d=0.06"
        if a.tempo != 1.0:
            af += f",atempo={a.tempo}"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(takes[k]), "-af", af, "-ac", "1", "-ar", "48000", str(f)], check=True)
        parts.append(f)
        seg_len.append(dur(f))
        print(f"line {i:2d}: take {k + 1}  {s:7.2f}-{e:7.2f}  -> {seg_len[-1]:.2f}s")
    # scene i holds its line plus the gap that follows; the first scene also holds the intro, the last the outro
    durs = [seg_len[i] + GAP for i in range(n)]
    durs[0] += INTRO
    durs[-1] += OUTRO - GAP
    starts, t = [], 0.0
    for i in range(n):
        starts.append(t + (INTRO if i == 0 else 0))
        t += durs[i]
    # voice track: silence + each line at its start time
    inputs, filt = [], []
    for i, f in enumerate(parts):
        inputs += ["-i", str(f)]
        filt.append(f"[{i}:a]adelay={int(starts[i] * 1000)}:all=1[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0,"
                "highpass=f=80,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=120,"
                f"loudnorm=I=-16:TP=-1.5:LRA=11,apad,atrim=0:{sum(durs):.3f}[out]")
    voice = tmp / "voice.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[out]",
                    "-ar", "48000", str(voice)], check=True)
    pngs = sorted(SCENES.glob("*.png"))
    assert len(pngs) == n, "render the scenes first: python -m submission.video.build_video"
    out = HERE / "Paradox_idea_video_voiced.mp4"
    assemble(pngs, durs, out, voice)
    (HERE / "voiced_timing.json").write_text(json.dumps(
        [{"scene": i, "take": pick[i] + 1, "voice_start": round(starts[i], 2), "voice_end": round(starts[i] + seg_len[i], 2),
          "scene_start": round(sum(durs[:i]), 2), "scene_end": round(sum(durs[:i + 1]), 2)} for i in range(n)], indent=1), encoding="utf-8")
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    print("saved", out, "length", round(sum(durs), 1), "s")


if __name__ == "__main__":
    main()
