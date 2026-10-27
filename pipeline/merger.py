import glob
import logging
import os
import random
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import List

logger = logging.getLogger("pipeline.merger")
ALLOWED_TRANSITIONS = ["fade", "pixelize", "dissolve", "circleopen", "wipeleft", "wiperight", "slideright", "radial"]

def _run(cmd: List[str]):
    logger.debug("RUN: " + " ".join(shlex.quote(str(x)) for x in cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{result.stderr[-2000:]}")


def _duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True,
    )
    try:
        return float((result.stdout or "0").strip() or 0)
    except ValueError:
        return 0.0


def _scene_sort_key(path: str):
    name = os.path.basename(path)
    m = re.search(r"_scene_(\d+)_", name)
    return (int(m.group(1)) if m else 10 ** 9, name)


def _concat_no_transition(inputs: List[str], output: str, fps: int):
    if len(inputs) == 1:
        shutil.copy2(inputs[0], output)
        return

    # ── Fast path: stream-copy concat (NO re-encode) ──────────────────────────
    # All scenes are rendered with identical params, so the concat demuxer can
    # copy them straight through in seconds instead of re-encoding for minutes.
    list_path = os.path.join(os.path.dirname(output), f"concat_{int(time.time()*1000)}.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in inputs:
            safe = p.replace("'", "'\\''")
            f.write(f"file '{safe}'\n")
    copied = False
    try:
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
              "-c", "copy", "-movflags", "+faststart", output])
        copied = True
    except RuntimeError:
        logger.warning("concat -c copy failed — falling back to re-encode")
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass
    if copied:
        return

    # ── Fallback: filter_complex concat re-encode (robust but slower) ─────────
    cmd = ["ffmpeg", "-y"]
    for p in inputs:
        cmd += ["-i", p]

    filter_parts = []
    concat_inputs = []
    for i in range(len(inputs)):
        filter_parts.append(f"[{i}:v]fps={fps},format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v{i}]")
        filter_parts.append(
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]"
        )
        concat_inputs.append(f"[v{i}][a{i}]")

    filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(inputs)}:v=1:a=1[v][a]")

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        output,
    ]
    _run(cmd)


def _merge_batch_with_transitions(
    inputs: List[str],
    output: str,
    fps: int,
    td: float,
    work_dir: str,
    global_start_index: int = 0,
):
    if len(inputs) == 1:
        shutil.copy2(inputs[0], output)
        return

    cmd = ["ffmpeg", "-y"]
    for p in inputs:
        cmd += ["-i", p]

    filter_parts = []
    for i in range(len(inputs)):
        filter_parts.append(f"[{i}:v]fps={fps},format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v{i}]")

    offset = max(_duration(inputs[0]) - td, 0.0)
    prev_v = "v0"

    for i in range(1, len(inputs)):
        out_v = f"vx{i}"
        t = random.choice(ALLOWED_TRANSITIONS)
        filter_parts.append(
            f"[{prev_v}][v{i}]xfade=transition={t}:duration={td}:offset={offset}[{out_v}]"
        )
        offset = max(offset + _duration(inputs[i]) - td, 0.0)
        prev_v = out_v

    # Audio: crossfade instead of trim+concat — the old atrim approach cut the
    # last `td` seconds of EVERY scene's voiceover (scene length == audio length).
    for i in range(len(inputs)):
        filter_parts.append(
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]"
        )
    prev_a = "a0"
    for i in range(1, len(inputs)):
        out_a = f"ax{i}"
        filter_parts.append(f"[{prev_a}][a{i}]acrossfade=d={td}[{out_a}]")
        prev_a = out_a

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{prev_v}]",
        "-map", f"[{prev_a}]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        output,
    ]
    _run(cmd)


def _merge_round(
    inputs: List[str],
    level: int,
    work_dir: str,
    fps: int,
    td: float,
    batch_size: int = 8,
) -> List[str]:
    outputs = []
    for i in range(0, len(inputs), batch_size):
        chunk = inputs[i : i + batch_size]
        out_path = os.path.join(work_dir, f"lvl{level}_{i//batch_size:03d}.mp4")
        if td <= 0:
            _concat_no_transition(chunk, out_path, fps)
        else:
            _merge_batch_with_transitions(chunk, out_path, fps, td, work_dir, global_start_index=i)
        outputs.append(out_path)
    return outputs


def merge_scenes(
    scene_dir: str,
    output_path: str,
    fps: int = 30,
    transition_duration: float = 0.0,
):
    files = sorted(
        glob.glob(os.path.join(scene_dir, "*.mp4")),
        key=_scene_sort_key,
    )

    if not files:
        raise RuntimeError(f"No scene videos found in {scene_dir}")

    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        raise RuntimeError(f"Missing scene files: {missing}")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if len(files) == 1:
        shutil.copy2(files[0], output_path)
        logger.info(f"Single scene — copied directly to {output_path}")
        return

    work_dir = os.path.join(os.path.dirname(output_path), f".merge_tmp_{int(time.time())}")
    os.makedirs(work_dir, exist_ok=True)

    logger.info(f"Merging {len(files)} scene videos with transitions...")
    try:
        current = files
        level = 0
        while len(current) > 1:
            current = _merge_round(current, level, work_dir, fps, transition_duration)
            level += 1

        shutil.move(current[0], output_path)
    finally:
        # A half-written merge tree is GBs of dead weight — drop it even when
        # the merge raised, so a retry doesn't run into a full disk.
        shutil.rmtree(work_dir, ignore_errors=True)

    logger.info(f"Merge complete → {output_path}")
