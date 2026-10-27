"""Motion-graphic cards (date stamps, counters, name/quote/chapter cards).

Each scene's `graphic` (authored by the script model) is rendered once per
video as a transparent 1080x1920 WebM from motion_templates/ (HyperFrames),
then overlaid on that scene's picture in render_motion_video. One batch call
per video keeps headless Chrome warm across cards. Any failure just means the
video ships without cards — never a failed scene.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict

logger = logging.getLogger("pipeline.motion_graphics")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "motion_templates"
RENDER_TIMEOUT = 900
HYPERFRAMES = "hyperframes@0.8.188"  # pinned: CI and local render identically


async def render_graphics(scenes, accent_hex: str, out_dir: Path) -> Dict[int, str]:
    """Render every scene's card; returns {scene_no: webm_path} for the ones that exist."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = {s.scene_no: s.graphic for s in scenes if getattr(s, "graphic", None)}
    paths = {n: out_dir / f"graphic_{n}.webm" for n in wanted}
    rows = [
        {"name": f"graphic_{n}", "kind": g["type"], "title": g["title"],
         "subtitle": g.get("subtitle", ""), "accent": accent_hex}
        for n, g in wanted.items() if not paths[n].is_file()
    ]
    if rows:
        rows_file = out_dir / "graphics_rows.json"
        rows_file.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
        npx = "npx.cmd" if os.name == "nt" else "npx"
        cmd = [npx, "--yes", HYPERFRAMES, "render", "--batch", str(rows_file),
               "--output", str(out_dir / "{name}.webm"),
               "--format", "webm", "--quality", "draft", "--fps", "30"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(TEMPLATES_DIR),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), RENDER_TIMEOUT)
            if proc.returncode != 0:
                logger.warning(f"Graphics render exited {proc.returncode}: {out.decode(errors='ignore')[-600:]}")
        except Exception as e:
            logger.warning(f"Graphics render failed — continuing without cards: {e}")
    done = {n: str(p) for n, p in paths.items() if p.is_file() and p.stat().st_size > 0}
    logger.info(f"Motion graphics: {len(done)}/{len(wanted)} cards ready")
    return done
