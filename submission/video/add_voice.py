"""Puts a recorded voice-over onto the idea video.

    python -m submission.video.add_voice path/to/voiceover.webm [--offset 0.0]

The studio page starts the recording and the video together, so the voice lines up as recorded.
--offset shifts the voice (positive = later, negative = earlier) if a take needs nudging.
The voice is cleaned up (low rumble removed, gentle compression, loudness normalised for web video).
Writes submission/video/Paradox_idea_video_voiced.mp4.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--offset", type=float, default=0.0)
    a = ap.parse_args()
    video, out = HERE / "Paradox_idea_video.mp4", HERE / "Paradox_idea_video_voiced.mp4"
    shift = f"adelay={int(a.offset * 1000)}:all=1," if a.offset > 0 else (f"atrim=start={-a.offset},asetpts=PTS-STARTPTS," if a.offset < 0 else "")
    af = shift + "highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=120,loudnorm=I=-16:TP=-1.5:LRA=11,apad"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", a.audio, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest",
                    "-movflags", "+faststart", str(out)], check=True)
    print("saved", out)


if __name__ == "__main__":
    main()
