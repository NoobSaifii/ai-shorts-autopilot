"""QA verification for a generated video.

Usage:
    python scripts/verify_video.py "<path-to-final-video.mp4>"

Checks: codec/resolution/fps, audio format, duration window, loudness (-14 LUFS).
"""

import json
import re
import subprocess
import sys


def ffprobe_streams(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True,
    )
    return json.loads(out.stdout or "{}")


def measure_loudness(path: str) -> dict:
    out = subprocess.run(
        ["ffmpeg", "-i", path, "-af",
         "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    stderr = out.stderr or ""
    start, end = stderr.rfind("{"), stderr.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(stderr[start:end + 1])
    except json.JSONDecodeError:
        return {}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    path = sys.argv[1]

    info = ffprobe_streams(path)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = float(info.get("format", {}).get("duration", 0))

    results = []

    def check(name, cond, actual):
        results.append((name, cond, actual))
        print(f"  {'PASS' if cond else 'FAIL'}  {name}: {actual}")

    print(f"Verifying: {path}\n")
    check("video codec h264", v.get("codec_name") == "h264", v.get("codec_name"))
    check("resolution 1080x1920", (v.get("width"), v.get("height")) == (1080, 1920),
          f"{v.get('width')}x{v.get('height')}")
    fps_raw = v.get("r_frame_rate", "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = round(float(num) / float(den), 2)
    except Exception:
        fps = 0
    check("fps 30", abs(fps - 30) < 0.6, fps)
    check("audio aac", a.get("codec_name") == "aac", a.get("codec_name"))
    check("audio 44100 Hz", a.get("sample_rate") == "44100", a.get("sample_rate"))
    check("audio stereo", a.get("channels") == 2, a.get("channels"))
    check("duration 110-150s (target window)", 110 <= duration <= 150, f"{duration:.1f}s")
    if not (110 <= duration <= 150):
        check("duration hard limit <=176s", duration <= 176, f"{duration:.1f}s")

    print("\nMeasuring loudness (takes a moment)...")
    ln = measure_loudness(path)
    if ln:
        i = float(ln.get("input_i", -99))
        tp = float(ln.get("input_tp", 0))
        check("integrated loudness -14 LUFS ±1", -15.0 <= i <= -13.0, f"{i:.1f} LUFS")
        check("true peak <= -1.0 dBTP", tp <= -1.0, f"{tp:.1f} dBTP")
    else:
        check("loudness measurable", False, "no loudnorm stats")

    failed = [r for r in results if not r[1]]
    print(f"\n{'ALL CHECKS PASSED' if not failed else f'{len(failed)} CHECK(S) FAILED'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
