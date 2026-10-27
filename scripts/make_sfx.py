"""Synthesize the cinematic SFX library with ffmpeg (CC0 by construction —
generated procedurally, no third-party material). Re-run any time to rebuild.

Creates:
    assets/sfx/boom/boom_{1..3}.mp3        deep sub impacts (scene-1 hook)
    assets/sfx/whoosh/whoosh_{1..3}.mp3    transition swipes (energy jumps)
    assets/sfx/riser/riser_{1..2}.mp3      tension builds (into final scene)
    assets/sfx/heartbeat/heartbeat_1.mp3   slow heartbeat loop (optional)

Implementation notes: envelopes use volume=...:eval=frame (the aeval filter
segfaults on some ffmpeg 8.x builds); every lavfi source is generated at
44100 Hz so amix never sees mismatched rates. Commas inside expressions are
escaped (\\,) so the filter-graph parser doesn't split on them.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SFX = ROOT / "assets" / "sfx"

FMT = "aformat=sample_rates=44100:channel_layouts=stereo"


def run(args: list, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + args + ["-b:a", "192k", str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAIL {dest.name} (rc={r.returncode})\n{(r.stderr or '(no stderr)')[-1200:]}")
        return False
    size = dest.stat().st_size
    print(f"OK   {dest.relative_to(ROOT)}  ({size//1024}KB)")
    return size > 4000


def boom(dest: Path, freq: float, dur: float, decay: float):
    """Sub-bass sine drop + filtered brown-noise thump, long tail."""
    fc = (
        f"[0:a]volume='exp(-{decay}*t)':eval=frame[s];"
        f"[1:a]lowpass=f=150,volume='exp(-7*t)':eval=frame[n];"
        f"[s][n]amix=inputs=2:normalize=0,"
        f"bass=g=7:f={int(freq + 5)},alimiter=limit=0.92:level=false,{FMT}"
    )
    return run(
        ["-f", "lavfi", "-i", f"sine=f={freq}:d={dur}:r=44100",
         "-f", "lavfi", "-i", f"anoisesrc=color=brown:d={dur}:amplitude=0.6:r=44100",
         "-filter_complex", fc],
        dest,
    )


def whoosh(dest: Path, dur: float, lo: int, hi: int, color: str):
    """Band-passed noise with a sin² swell-and-die envelope."""
    af = (
        f"highpass=f={lo},lowpass=f={hi},"
        f"volume='pow(sin(PI*t/{dur})\\,2)':eval=frame,"
        f"alimiter=limit=0.9:level=false,{FMT}"
    )
    return run(
        ["-f", "lavfi", "-i", f"anoisesrc=color={color}:d={dur}:amplitude=0.85:r=44100",
         "-af", af],
        dest,
    )


def riser(dest: Path, dur: float, f0: int, sweep: int):
    """Rising chirp + noise crescendo → cut at peak."""
    fc = (
        f"[1:a]highpass=f=260,lowpass=f=3000,"
        f"volume='pow(t/{dur}\\,2.2)':eval=frame[n];"
        f"[0:a]volume='pow(t/{dur}\\,1.5)':eval=frame[c];"
        f"[c][n]amix=inputs=2:normalize=0,"
        f"alimiter=limit=0.9:level=false,{FMT}"
    )
    return run(
        ["-f", "lavfi", "-i",
         f"aevalsrc='0.4*sin(2*PI*({f0}*t+{sweep}*t*t))':d={dur}:s=44100",
         "-f", "lavfi", "-i", f"anoisesrc=color=pink:d={dur}:amplitude=0.7:r=44100",
         "-filter_complex", fc],
        dest,
    )


def heartbeat(dest: Path, dur: float = 8.0, bpm: float = 56.0):
    """Lub-dub pattern: low sine bursts with exponential envelopes."""
    period = 60.0 / bpm
    af = f"lowpass=f=95,alimiter=limit=0.9:level=false,{FMT}"
    expr = (
        f"0.85*sin(2*PI*50*t)*("
        f"exp(-30*mod(t\\,{period:.3f}))"
        f"+0.6*exp(-30*abs(mod(t\\,{period:.3f})-0.17)))"
    )
    return run(
        ["-f", "lavfi", "-i", f"aevalsrc='{expr}':d={dur}:s=44100", "-af", af],
        dest,
    )


def main():
    ok = True
    ok &= boom(SFX / "boom" / "boom_1.mp3", 52, 1.8, 2.5)
    ok &= boom(SFX / "boom" / "boom_2.mp3", 46, 2.0, 2.2)
    ok &= boom(SFX / "boom" / "boom_3.mp3", 58, 1.5, 3.0)
    ok &= whoosh(SFX / "whoosh" / "whoosh_1.mp3", 0.65, 400, 3200, "pink")
    ok &= whoosh(SFX / "whoosh" / "whoosh_2.mp3", 0.50, 600, 4500, "white")
    ok &= whoosh(SFX / "whoosh" / "whoosh_3.mp3", 0.80, 300, 2400, "pink")
    ok &= riser(SFX / "riser" / "riser_1.mp3", 3.0, 70, 45)
    ok &= riser(SFX / "riser" / "riser_2.mp3", 2.4, 90, 70)
    ok &= heartbeat(SFX / "heartbeat" / "heartbeat_1.mp3")
    print("\nALL SFX OK" if ok else "\nSOME SFX FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
