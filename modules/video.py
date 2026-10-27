import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("pipeline.video")

# Pixel offsets are written against the ORIGINAL ~1080-wide input and get
# multiplied by {ss} (supersample factor) at selection time, because the
# zoompan input frame is now supersample× larger.
MOTION_POOL = [
    {
        "desc": "cinematic_snap_zoom_in",
        "zoom": "if(lt(on,10),1.05,1.20+0.02*sin(on/10))",
        "x": "iw/2-(iw/zoom/2)+15*{ss}*sin(on/25)",
        "y": "ih/2-(ih/zoom/2)+10*{ss}*cos(on/30)",
    },
    {
        "desc": "handheld_camera_shake",
        "zoom": "1.15",
        "x": "iw/2-(iw/zoom/2)+12*{ss}*sin(on/3)+8*{ss}*cos(on/5)",
        "y": "ih/2-(ih/zoom/2)+10*{ss}*cos(on/4)+5*{ss}*sin(on/2)",
    },
    {
        "desc": "fast_push_in",
        "zoom": "min(1.05+0.35*(on/{frames}),1.35)",
        "x": "iw/2-(iw/zoom/2)",
        "y": "ih/2-(ih/zoom/2)",
    },
    {
        "desc": "dramatic_pull_out_shake",
        "zoom": "max(1.30-0.25*(on/{frames}),1.05)",
        "x": "iw/2-(iw/zoom/2)+8*{ss}*sin(on/4)",
        "y": "ih/2-(ih/zoom/2)+8*{ss}*cos(on/5)",
    },
    {
        "desc": "impact_thud",
        "zoom": "if(lt(on,5),1.05,if(lt(on,15),1.25,1.15))",
        "x": "iw/2-(iw/zoom/2)+20*{ss}*sin(on)*exp(-on/10)",
        "y": "ih/2-(ih/zoom/2)+20*{ss}*cos(on)*exp(-on/10)",
    },
    {
        "desc": "creepy_slow_pan",
        "zoom": "1.18",
        "x": "iw/2-(iw/zoom/2)+(on/{frames})*120*{ss}",
        "y": "ih/2-(ih/zoom/2)+5*{ss}*sin(on/20)",
    },
    {
        "desc": "intense_heartbeat",
        "zoom": "1.10+0.08*sin(on/4)*exp(-mod(on,20)/5)",
        "x": "iw/2-(iw/zoom/2)",
        "y": "ih/2-(ih/zoom/2)",
    },
    {
        "desc": "breathing_zoom",
        "zoom": "1.10+0.03*sin(on/15)",
        "x": "iw/2-(iw/zoom/2)",
        "y": "ih/2-(ih/zoom/2)+4*{ss}*sin(on/25)",
    },
    {
        "desc": "parallax_glide",
        "zoom": "1.12",
        "x": "iw/2-(iw/zoom/2)+(1-on/{frames})*90*{ss}-45*{ss}",
        "y": "ih/2-(ih/zoom/2)+3*{ss}*sin(on/18)",
    },
    {
        "desc": "crash_zoom_pulse",
        "zoom": "if(lt(on,8),1.05+0.03*on,1.28+0.02*sin(on/6))",
        "x": "iw/2-(iw/zoom/2)+6*{ss}*sin(on/2)*exp(-on/12)",
        "y": "ih/2-(ih/zoom/2)+6*{ss}*cos(on/2)*exp(-on/12)",
    },
]

_MOTION_BY_NAME = {m["desc"]: m for m in MOTION_POOL}

# Per-mood cinematic color grades (channel identity — same mood groups as the
# music library). colorbalance pushes shadows/mids/highs; eq sets the tone curve.
MOOD_GRADES = {
    # cold blue-teal shadows, slightly crushed — investigation files
    "dark_mystery":  "colorbalance=bs=0.08:gs=0.04:bh=-0.02,"
                     "eq=contrast=1.18:saturation=1.04:gamma=0.94:brightness=-0.015",
    # sickly green-cyan, desaturated — horror
    "eerie_horror":  "colorbalance=gs=0.07:gm=0.03:bs=0.04,"
                     "eq=contrast=1.16:saturation=0.92:gamma=0.96",
    # teal-orange blockbuster — epic history
    "epic_history":  "colorbalance=bs=0.10:rm=0.03:rh=0.07:bh=-0.05,"
                     "eq=contrast=1.17:saturation=1.22:gamma=0.95",
    # clean cool high-contrast — science/psychology
    "tense_science": "colorbalance=bs=0.05:bm=0.02:bh=0.03,"
                     "eq=contrast=1.22:saturation=1.08:gamma=0.97",
}
DEFAULT_GRADE = "eq=contrast=1.15:saturation=1.2:gamma=0.95"


# ── Director Mode: per-scene voice tone → speed factor + voice EQ snippet ────
# speed multiplies the channel base speed (clamped); eq is inserted into the
# voiceover chain so each scene's delivery actually sounds different.
VOICE_TONE_SPEED = {
    "neutral": 1.00, "calm": 0.97, "somber": 0.93, "ominous": 0.92,
    "whisper": 0.95, "tense": 1.03, "urgent": 1.08, "intense": 1.05,
    "dramatic": 0.98, "awe": 0.96, "sinister": 0.93, "warning": 1.04,
}
VOICE_TONE_EQ = {
    "neutral": "",
    "calm": "volume=0.92",
    "somber": "volume=0.93,bass=g=2:f=120",
    "ominous": "volume=1.0,bass=g=3:f=100",
    "sinister": "volume=0.97,bass=g=3:f=95",
    "whisper": "volume=0.80,highpass=f=120,acompressor=threshold=0.1:ratio=4:makeup=2",
    "tense": "volume=1.03",
    "urgent": "volume=1.05,acompressor=threshold=0.09:ratio=4:makeup=2",
    "intense": "volume=1.06,bass=g=1:f=120,acompressor=threshold=0.08:ratio=4:makeup=3",
    "dramatic": "volume=1.0,bass=g=2:f=120",
    "awe": "volume=1.0,treble=g=1.5:f=6000",
    "warning": "volume=1.05",
}


def tone_speed_factor(tone: str) -> float:
    return VOICE_TONE_SPEED.get(str(tone or "").strip().lower(), 1.0)


def ass_color_to_rgb_hex(ass_color: str) -> str:
    """ASS '&H00BBGGRR' (BGR) → ffmpeg '0xRRGGBB'."""
    import re as _re
    hexpart = _re.sub(r"[^0-9A-Fa-f]", "", ass_color or "")
    hexpart = hexpart[-6:] if len(hexpart) >= 6 else "00D7FF"
    bb, gg, rr = hexpart[0:2], hexpart[2:4], hexpart[4:6]
    return f"0x{rr}{gg}{bb}"

# scene_energy (from the Gemini script) → motion subset.
# Calm scenes drift, intense scenes punch.
ENERGY_MOTION = {
    "low":     ["creepy_slow_pan", "breathing_zoom", "parallax_glide"],
    "medium":  ["cinematic_snap_zoom_in", "fast_push_in", "parallax_glide", "dramatic_pull_out_shake"],
    "high":    ["handheld_camera_shake", "fast_push_in", "impact_thud"],
    "maximum": ["impact_thud", "crash_zoom_pulse", "intense_heartbeat"],
}


def _normalize_energy(energy: str) -> str:
    e = str(energy or "").strip().lower()
    if e in ("max", "maximum", "very high", "extreme"):
        return "maximum"
    if e in ENERGY_MOTION:
        return e
    return "medium"


def select_motion(scene_no: int, frames: int, fps: int, energy: str = "medium",
                  ss: float = 2.0, force: str = "") -> dict:
    frames = max(frames, 2)
    frames15 = max(int(frames * 0.15), 1)
    if force and force in _MOTION_BY_NAME:
        m = _MOTION_BY_NAME[force]
    else:
        subset_names = ENERGY_MOTION[_normalize_energy(energy)]
        # Deterministic but well-scattered pick (stable across resume re-runs)
        idx = (scene_no * 2654435761) % len(subset_names)
        m = _MOTION_BY_NAME[subset_names[idx]]

    def _sub(expr: str) -> str:
        return (
            expr.replace("{frames15}", str(frames15))
                .replace("{frames}", str(frames))
                .replace("{ss}", f"{ss:g}")
        )

    return {
        "desc": m["desc"],
        "zoom": _sub(m["zoom"]),
        "x": _sub(m["x"]),
        "y": _sub(m["y"]),
    }


async def _run_ffmpeg(cmd: list, desc: str = "") -> str:
    """Run ffmpeg, raise on failure, return full stderr (ffmpeg logs there)."""
    loop = asyncio.get_event_loop()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    err = stderr.decode(errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed [{desc}]:\n{err[-2000:]}")
    logger.debug(f"FFmpeg OK [{desc}]")
    return err


def _escape_filter_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:")


async def render_motion_video(
    image_path: str,
    duration: float,
    zoom_expr: str,
    x_expr: str,
    y_expr: str,
    ass_path: str,
    fps: int,
    output_path: str,
    quality_preset: str = "veryfast",
    use_gpu: bool = False,
    crf: int = 16,
    supersample: float = 1.5,
    fonts_dir: Optional[str] = None,
    grade: str = "",
    flash_in: bool = False,
    finish: bool = False,
    overlay_path: str = "",
):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    ass_escaped = _escape_filter_path(ass_path)

    # Supersample the INPUT before zoompan: pan/zoom math then has sub-pixel
    # precision at the 1080×1920 output → kills the classic zoompan jitter.
    ss = max(1.0, float(supersample))
    ss_w = int(1080 * ss) // 2 * 2
    ss_h = int(1920 * ss) // 2 * 2

    ass_filter = f"ass='{ass_escaped}'"
    if fonts_dir and Path(fonts_dir).is_dir():
        ass_filter += f":fontsdir='{_escape_filter_path(str(fonts_dir))}'"

    # White-flash on impact cuts (maximum-energy scene openers)
    flash = "fade=t=in:st=0:d=0.08:color=white," if flash_in else ""

    # Cinematic finishing: crisp detail + subtle lens chromatic aberration.
    # Single-chain (no split/blend) so it stays cheap on a 2-core runner.
    cinematic = "unsharp=5:5:0.8:3:3:0.0,rgbashift=rh=2:bh=-2," if finish else ""

    vf = (
        f"scale={ss_w}:{ss_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={ss_w}:{ss_h},"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d=1:s=1080x1920:fps={fps},"
        f"{grade or DEFAULT_GRADE},"
        f"{cinematic}"
        f"{flash}"
        f"noise=alls=5:allf=t+u,"
        f"vignette=PI/3,"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-t", f"{duration:.3f}",
        "-i", image_path,
    ]
    if overlay_path and Path(overlay_path).is_file():
        # Motion-graphic card (transparent VP9): the libvpx decoder keeps its
        # alpha; it lands after the cut and sits under the captions.
        cmd += ["-c:v", "libvpx-vp9", "-itsoffset", "0.15", "-i", overlay_path,
                "-filter_complex",
                f"[0:v]{vf}null[bg];[bg][1:v]overlay=0:0:eof_action=pass:format=auto,{ass_filter}[v]",
                "-map", "[v]"]
    else:
        cmd += ["-vf", vf + ass_filter]
    cmd += ["-r", str(fps), "-pix_fmt", "yuv420p"]

    if use_gpu:
        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "24"])  # NVENC for high speed
    else:
        cmd.extend(["-c:v", "libx264", "-preset", quality_preset, "-crf", str(crf)])

    cmd.append(output_path)

    await _run_ffmpeg(cmd, "render_motion scene")


async def mux_audio_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    voice_gain: float = 1.0,
    tone: str = "neutral",
):
    """Mux the scene voiceover onto the silent motion video.

    Voice chain: clean documentary-style presence — high-pass rumble cut,
    gentle compression, mild warmth, brick-wall limiter. No echo (muddy),
    no per-scene SFX (sound design happens once at the final mix). A per-scene
    Director-Mode `tone` EQ is inserted so each scene's delivery sounds distinct.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Measure video duration up front so we can hard-pin the output to it.
    # -shortest alone is unreliable here: with -c:v copy, some FFmpeg builds
    # use the raw INPUT container duration (= audio length, shorter than video)
    # instead of the filtered output duration, silently trimming the scene's
    # visual tail and making the cut feel abrupt.
    vid_dur = await get_video_duration(video_path)
    if vid_dur <= 0:
        vid_dur = 10.0

    tone_eq = VOICE_TONE_EQ.get(str(tone or "").strip().lower(), "")
    tone_part = f"{tone_eq}," if tone_eq else ""
    voice_filter = (
        "[1:a]highpass=f=75,"
        "acompressor=threshold=0.125:ratio=3:attack=10:release=150:makeup=1.4,"
        "bass=g=2:f=130,"
        f"{tone_part}"
        f"volume={voice_gain:g},"
        "alimiter=limit=0.95:level=false,"
        "aresample=48000,aformat=channel_layouts=stereo,"
        f"apad=pad_dur={vid_dur:.3f}[voice]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", voice_filter,
        "-map", "0:v:0",
        "-map", "[voice]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        "-t", f"{vid_dur:.3f}",
        output_path,
    ]
    await _run_ffmpeg(cmd, "mux_audio_video")


def _parse_loudnorm_stats(stderr: str) -> Optional[dict]:
    """Extract the JSON block loudnorm prints at the end of ffmpeg stderr."""
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        stats = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None
    required = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    if not all(k in stats for k in required):
        return None
    try:
        if not all(abs(float(stats[k])) < 99 for k in required):
            return None  # -inf / nonsense (e.g. pure silence)
    except (TypeError, ValueError):
        return None
    return stats


async def add_background_music(
    video_path: str,
    music_path: Optional[str],
    output_path: str,
    voice_volume: float = 1.0,
    music_volume: float = 0.15,
    sfx_events: Optional[List[Tuple[float, str, float]]] = None,
    duration: float = 0.0,
    progress_bar_color: str = "",
    watermark_text: str = "",
    fonts_dir: str = "",
):
    """Final mix: voice + sidechain-ducked music (with intro/outro swells) +
    timed SFX, normalized to -14 LUFS via two-pass loudnorm. Optionally burns
    an animated progress bar and a subtle channel watermark into the video
    (one extra encode — skipped when both are disabled → stream copy).

    sfx_events: list of (time_seconds, file_path, volume).
    music_path may be None — voice + SFX still get the loudnorm master pass.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Legacy configs carried an inaudible 0.015 — floor it to the new default.
    if music_volume < 0.05:
        logger.info(f"music_volume {music_volume} is legacy-low — using 0.15")
        music_volume = 0.15

    sfx_events = [
        (t, f, v) for (t, f, v) in (sfx_events or []) if f and Path(f).is_file()
    ]
    has_music = bool(music_path) and Path(music_path).is_file()
    has_duration = duration and duration > 4.0

    cmd_inputs = ["-i", video_path]
    if has_music:
        cmd_inputs += ["-stream_loop", "-1", "-i", music_path]
    sfx_input_start = 2 if has_music else 1
    for _, sfx_file, _ in sfx_events:
        cmd_inputs += ["-i", sfx_file]

    parts = []
    mix_streams = []

    if has_music:
        parts.append(
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={voice_volume:g},asplit=2[vo][sc]"
        )
        # Music swells in over the hook and fades out under the closer
        music_fades = ",afade=t=in:st=0:d=1.2"
        if has_duration:
            music_fades += f",afade=t=out:st={max(duration - 2.2, 0):.3f}:d=2.0"
        parts.append(
            "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={music_volume:g}{music_fades}[mu]"
        )
        parts.append(
            "[mu][sc]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[duck]"
        )
        mix_streams = ["[vo]", "[duck]"]
    else:
        parts.append(
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={voice_volume:g}[vo]"
        )
        mix_streams = ["[vo]"]

    for i, (t, _, vol) in enumerate(sfx_events):
        ms = max(0, int(t * 1000))
        parts.append(
            f"[{sfx_input_start + i}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"volume={vol:g},adelay={ms}|{ms}[fx{i}]"
        )
        mix_streams.append(f"[fx{i}]")

    if len(mix_streams) > 1:
        parts.append(
            f"{''.join(mix_streams)}amix=inputs={len(mix_streams)}:"
            "duration=first:dropout_transition=3:normalize=0[mix]"
        )
    else:
        parts.append(f"{mix_streams[0]}acopy[mix]")

    # ── Optional burned-in video layer: progress bar + watermark ────────────
    video_parts = []
    video_out = "0:v"
    bar_input_idx = sfx_input_start + len(sfx_events)
    if progress_bar_color and has_duration:
        cmd_inputs += [
            "-f", "lavfi",
            "-i", f"color=c={progress_bar_color}@0.85:s=1080x12:r=30:d={duration:.3f}",
        ]
        video_parts.append(
            f"[{video_out}][{bar_input_idx}:v]"
            f"overlay=x='-w+w*t/{duration:.3f}':y=H-h:eval=frame[vbar]"
        )
        video_out = "vbar"
    if watermark_text:
        font_file = Path(fonts_dir or "assets/fonts") / "Anton-Regular.ttf"
        if font_file.is_file():
            safe_text = watermark_text.replace("\\", "").replace("'", "").replace(":", "")
            video_parts.append(
                f"[{video_out}]drawtext=fontfile='{_escape_filter_path(str(font_file))}'"
                f":text='{safe_text}':fontcolor=white@0.38:fontsize=30"
                f":shadowcolor=black@0.5:shadowx=1:shadowy=1"
                f":x=w-tw-42:y=96[vwm]"
            )
            video_out = "vwm"
    burn_video = bool(video_parts)

    audio_graph = ";".join(parts)
    loudnorm_target = "loudnorm=I=-14:TP=-1.5:LRA=11"

    # ── Pass 1: measure (audio-only graph) ───────────────────────────────────
    measure_graph = f"{audio_graph};[mix]{loudnorm_target}:print_format=json[ln]"
    measure_cmd = (
        ["ffmpeg", "-y"] + cmd_inputs
        + ["-filter_complex", measure_graph, "-map", "[ln]", "-f", "null", "-"]
    )
    stats = None
    try:
        stderr = await _run_ffmpeg(measure_cmd, "loudnorm_measure")
        stats = _parse_loudnorm_stats(stderr)
    except Exception as e:
        logger.warning(f"loudnorm measure pass failed (using dynamic mode): {e}")

    if stats:
        final_loudnorm = (
            f"{loudnorm_target}"
            f":measured_I={stats['input_i']}"
            f":measured_TP={stats['input_tp']}"
            f":measured_LRA={stats['input_lra']}"
            f":measured_thresh={stats['input_thresh']}"
            f":offset={stats['target_offset']}"
            f":linear=true"
        )
        logger.info(
            f"loudnorm: measured {stats['input_i']} LUFS / TP {stats['input_tp']} → -14 LUFS"
        )
    else:
        final_loudnorm = loudnorm_target
        logger.warning("loudnorm: no measured stats — falling back to single-pass dynamic")

    # ── Pass 2: render (audio graph + optional burned video layer) ──────────
    final_graph = ";".join(parts + video_parts) + f";[mix]{final_loudnorm}[aout]"
    cmd = ["ffmpeg", "-y"] + cmd_inputs + ["-filter_complex", final_graph]
    if burn_video:
        # Overlay burn (progress bar + watermark) needs a re-encode. Keep CRF 16
        # (same quality as the scenes) — only the preset is sped up; at a fixed
        # CRF the preset changes encode speed/size, not visual quality.
        cmd += [
            "-map", f"[{video_out}]",
            "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-pix_fmt", "yuv420p",
        ]
    else:
        cmd += [
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
        ]
    cmd += [
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",   # FB Reels spec wants 48kHz; loudnorm resamples to 192k — force back
        "-ac", "2",
        "-movflags", "+faststart",
        "-shortest",
        output_path,
    ]
    await _run_ffmpeg(cmd, "final_audio_mix")


async def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f"ffprobe failed: {stderr.decode().strip()}")
        return 0.0
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0


async def enforce_length_constraint(
    video_path: str,
    target_max_duration: float = 175.0,
    output_path: Optional[str] = None,
) -> str:
    """
    SAFETY NET ONLY: scripts are word-budgeted to land naturally under the
    target. Speed up video to fit within target_max_duration if they don't.
    If output_path is given, original is preserved and output is written separately.
    If output_path is None, original is overwritten (legacy behaviour).
    """
    duration = await get_video_duration(video_path)
    if duration <= target_max_duration:
        if output_path:
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path
        return video_path

    speed_factor = duration / target_max_duration
    if speed_factor > 1.06:
        logger.warning(
            f"Video {duration:.1f}s needs {speed_factor:.3f}x speed-up (>1.06x) — "
            f"script word budget overshot! Applying anyway for platform limit, "
            f"but check the prompt's TOTAL SPOKEN BUDGET LAW."
        )
    else:
        logger.info(f"Video {duration:.1f}s → speeding up {speed_factor:.3f}x to fit {target_max_duration}s")

    dest = output_path if output_path else video_path.replace(".mp4", "_spedup.mp4")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-filter_complex", f"[0:v]setpts={1/speed_factor}*PTS[v];[0:a]atempo={speed_factor}[a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "16",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        dest,
    ]
    await _run_ffmpeg(cmd, "enforce_length")

    if output_path is None:
        # Legacy: overwrite original
        Path(dest).replace(video_path)
        return video_path

    return dest
