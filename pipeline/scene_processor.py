import asyncio
import io
import logging
from pathlib import Path

from PIL import Image

from modules.audio_assets import resolve_mood
from modules.image_gen import ImageGenerator, AllProvidersExhausted
from modules.captions import generate_hormozi_ass
from modules.tts import KokoroClient
from modules.video import (
    MOOD_GRADES,
    _normalize_energy,
    mux_audio_video,
    render_motion_video,
    select_motion,
    tone_speed_factor,
)
from utils.database import Database
from utils.disk import purge
from utils.paths import ProjectPaths

logger = logging.getLogger("pipeline.scene")

# ── Per-channel fallback prompts ───────────────────────────────────────────────
# Used when the original AI-generated prompt is blocked by Cloudflare content
# policy (HTTP 500 / error 3030). Each channel gets 3 themed safe prompts that
# match its visual identity. All prompts are guaranteed content-filter-safe:
# no people, no violence, no gore, no real brands — just atmospheric scenery.

_CHANNEL_FALLBACKS: dict[str, list[str]] = {
    "Restricted Lore": [
        "masterpiece, best quality, cinematic aerial view of remote desert research facility at dusk, barbed wire fence casting long shadows, blood orange sky, volumetric fog, vertical 9:16, photorealistic, 8K, no people, no text, no logos",
        "masterpiece, best quality, abandoned underground bunker corridor, concrete walls, flickering emergency lighting, cold steel blue and deep shadow color grade, dust particles floating, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, redacted government document folder on dark wooden desk, single spotlight overhead, ash fall particles, deep teal and amber color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    ],
    "Classified Cognition": [
        "masterpiece, best quality, vintage psychology laboratory interior, clinical examination chair, cold overhead lighting, dust particles in air, cold steel blue and deep shadow color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, neural pathway visualization, glowing synaptic connections in dark void, electric blue and gold color grade, bioluminescence, vertical 9:16, photorealistic, 8K, no text",
        "masterpiece, best quality, dark observation corridor with one-way mirror, single overhead light casting sharp shadow, ground mist, ice blue and crimson color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    ],
    "Filed And Forgotten": [
        "masterpiece, best quality, detective investigation board with red string connecting clippings in dark room, single overhead light casting sharp shadows, blood orange and deep black color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, dusty cold case evidence boxes stacked in dim archive room, cobwebs on shelves, deep teal and amber color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, old newspaper clippings pinned to worn corkboard, yellowed and torn edges, single desk lamp glow, ice blue and crimson color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    ],
    "Ruined Clock": [
        "masterpiece, best quality, ancient stone civilization ruins at golden hour, crumbling columns half-buried in earth, volumetric god-rays through mist, deep teal and amber color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, underwater ancient stone city, bioluminescent creatures drifting through submerged archways, electric blue and gold color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, aerial view of jungle-covered ancient pyramid, morning mist rising from dense canopy, emerald and violet color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    ],
    "Fracture Layer": [
        "masterpiece, best quality, abandoned physics laboratory, tesla coil with electric arc glow, sparks shower across dark room, electric blue and gold color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, particle accelerator tunnel curving into darkness, concentric glowing rings of light, ice blue and crimson color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, bioluminescent microscopic organisms magnified, glowing cellular structures in dark void, deep teal and amber color grade, vertical 9:16, photorealistic, 8K, no text",
    ],
    "The Cursed Map": [
        "masterpiece, best quality, ancient overgrown temple at night, vines consuming crumbling stone walls, moonlight through broken roof, ground mist, deep teal and amber color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, desolate ancient crossroads at dusk, weathered stone road marker, stormy sky with ember particles, blood orange and deep black color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, ancient stone burial ground in rolling fog, weathered markers barely visible, smoke tendrils, bone white and slate charcoal color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    ],
    "Blade Archives": [
        "masterpiece, best quality, ancient stone forge with glowing molten metal in hearth, historical artifacts hanging on stone wall, sparks shower, rust orange and midnight blue color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, ancient armory interior, dust motes in god-rays through narrow stone window, relics resting on stone floor, cold steel blue and deep shadow color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, ancient stone fortress at dawn, morning mist rolling over battlements, ember particles drifting, blood orange and deep black color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    ],
    "Covered Pages": [
        "masterpiece, best quality, ancient library with towering bookshelves reaching into darkness, forbidden tomes, dust motes in god-rays through high window, deep teal and amber color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, historical archive room, yellowed documents in wooden filing cabinets, single candle flame, blood orange and deep shadow color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, pages of ancient manuscript curling in stone fireplace, ash fall, ember particles floating upward, ice blue and crimson color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    ],
    "Erased Lore": [
        "masterpiece, best quality, abandoned wartime concrete bunker interior, rusting equipment, single shaft of light through narrow window, cold steel blue and deep shadow color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, vintage wartime operations map room, large strategic map on wooden table with markers, warm lamp light, deep teal and amber color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, overgrown wartime fortification ruins deep in forest, moss-covered concrete, morning mist drifting between trees, emerald and violet color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    ],
    "Myth Bleed": [
        "masterpiece, best quality, ancient stone temple of forgotten deity, carved mythological reliefs on towering pillars, fire ember particles drifting, blood orange and deep black color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, sacred ritual stone altar with ceremonial offerings, smoke tendrils rising to starlit sky, deep teal and amber color grade, vertical 9:16, photorealistic, 8K, no people, no text",
        "masterpiece, best quality, mythological creature carved in ancient stone relief, dramatic torchlight shadows dancing across carved surface, bone white and slate charcoal color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    ],
}

# Generic fallbacks used when channel name is unknown
_GENERIC_FALLBACKS = [
    "masterpiece, best quality, cinematic dark atmospheric ancient stone ruins at dusk, volumetric god-rays through mist, deep teal and amber color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    "masterpiece, best quality, dramatic cinematic landscape, dark stormy sky over ancient mountains, ember particles, blood orange and deep black color grade, vertical 9:16, photorealistic, 8K, no people, no text",
    "masterpiece, best quality, cinematic underground cavern, bioluminescent moss on ancient stone walls, ground mist, electric blue and gold color grade, vertical 9:16, photorealistic, 8K, no people, no text",
]


def _make_fallback_image(width: int, height: int) -> bytes:
    """Last-resort plain dark image if even fallback prompts are blocked."""
    img = Image.new("RGB", (width, height), (18, 18, 28))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


async def process_scene(
    scene,
    job_id: str,
    config,
    db: Database,
    paths: ProjectPaths,
    image_gen: ImageGenerator,
    tts_client: KokoroClient,
    semaphore: asyncio.Semaphore,
    channel_name: str = "",
    hook_text: str = "",
    progress=None,
    progress_task=None,
) -> Path:
    async with semaphore:
        scene_no = scene.scene_no
        tag = f"[Scene {str(scene_no).zfill(2)}]"

        # ── Step 1: Image ─────────────────────────────────────────────────────
        if db.is_step_done(job_id, scene_no, "image"):
            image_path = Path(db.get_step_path(job_id, scene_no, "image"))
            logger.info(f"{tag} image: already done → {image_path.name}")
        else:
            safe_prompt = (
                str(scene.image_prompt or scene.scene_text)
                .replace("\n", " ")
                .replace("\r", " ")
                .replace('"', "'")
                .strip()
            )
            full_prompt = (
                f"{safe_prompt} vertical 9:16 portrait composition for reels and shorts "
                "subject centered mobile framing single subject only one face clean composition"
            )
            try:
                image_bytes = await image_gen.generate_image(
                    title=paths.title,
                    scene_no=scene_no,
                    prompt=full_prompt,
                    width=config["video"]["width"],
                    height=config["video"]["height"],
                )
                logger.info(f"{tag} image saved ({len(image_bytes)//1024}KB)")
            except AllProvidersExhausted as exc:
                w = config["video"]["width"]
                h = config["video"]["height"]

                if not exc.likely_content_block:
                    # ── Rate-limit exhaustion ──────────────────────────────────
                    # 35 workers failed but NOT because of content policy.
                    # This means all accounts are genuinely rate-limited right now.
                    # Themed fallback won't help — it will hit the same rate limit.
                    # Re-raise so the scene (and video) fails cleanly; pipeline
                    # will mark the job failed and resume on the next run.
                    logger.error(
                        f"{tag} ALL providers exhausted due to RATE LIMITING — "
                        f"no fallback attempted. Scene will fail and retry next run."
                    )
                    raise

                # ── Content policy block ───────────────────────────────────────
                # All 35 workers rejected the prompt (content filter, error 3030).
                # The prompt itself is the problem — not the workers.
                # Use channel-specific themed safe prompts instead.
                logger.warning(
                    f"{tag} CONTENT POLICY BLOCK detected — "
                    f"switching to {channel_name or 'generic'} themed fallback prompts."
                )
                fallbacks = _CHANNEL_FALLBACKS.get(channel_name, _GENERIC_FALLBACKS)
                image_bytes = None
                for i, fallback_prompt in enumerate(fallbacks, 1):
                    try:
                        image_bytes = await image_gen.generate_image(
                            title=paths.title,
                            scene_no=scene_no,
                            prompt=fallback_prompt,
                            width=w,
                            height=h,
                        )
                        logger.warning(
                            f"{tag} using {channel_name or 'generic'} themed fallback #{i}"
                        )
                        break
                    except AllProvidersExhausted:
                        continue
                if image_bytes is None:
                    # All channel fallbacks also blocked — absolute last resort
                    image_bytes = _make_fallback_image(w, h)
                    logger.warning(f"{tag} all fallback prompts blocked — using plain dark image")

            ext = "jpg"
            image_path = paths.image_path(scene_no, ext)
            image_path.write_bytes(image_bytes)
            db.mark_step_done(job_id, scene_no, "image", str(image_path))

        # ── Step 2: TTS Audio ─────────────────────────────────────────────────
        if db.is_step_done(job_id, scene_no, "audio_v2"):
            raw_audio = Path(db.get_step_path(job_id, scene_no, "audio_v2"))
            audio_duration = await tts_client.get_audio_duration(str(raw_audio))
            logger.info(f"{tag} audio: already done ({audio_duration:.2f}s)")
        else:
            raw_audio = paths.raw_audio_path(scene_no)
            # Director Mode: per-scene tone nudges the delivery speed
            base_speed = float(config["kokoro"]["speed"])
            tone = getattr(scene, "voice_tone", "neutral")
            eff_speed = max(0.70, min(1.18, base_speed * tone_speed_factor(tone)))
            tts_text = scene.voice_text or scene.scene_text
            audio_duration = await tts_client.generate_voiceover(
                text=tts_text,
                voice=config["kokoro"]["voice"],
                speed=eff_speed,
                output_path=str(raw_audio),
                voice_ref=config["kokoro"].get("voice_ref", ""),
            )
            db.mark_step_done(job_id, scene_no, "audio_v2", str(raw_audio))
            logger.info(f"{tag} audio saved ({audio_duration:.2f}s, tone={tone})")

            # Guard: if TTS returned near-silent audio (< 1s), the scene text
            # was likely blank or a single symbol — regenerate with fallback text
            # to avoid FFmpeg "Invalid data found" crash on the mux step.
            if audio_duration < 1.0:
                fallback_text = scene.scene_text or scene.voice_text or "This is a remarkable moment in history."
                logger.warning(
                    f"{tag} audio too short ({audio_duration:.2f}s) — regenerating with fallback text"
                )
                audio_duration = await tts_client.generate_voiceover(
                    text=fallback_text,
                    voice=config["kokoro"]["voice"],
                    speed=eff_speed,
                    output_path=str(raw_audio),
                    voice_ref=config["kokoro"].get("voice_ref", ""),
                )
                logger.info(f"{tag} fallback audio saved ({audio_duration:.2f}s)")


        # ── Step 3: Subtitles ─────────────────────────────────────────────────
        # Step keys are versioned: a job resumed across the pipeline
        # upgrade regenerates styling-dependent artifacts but reuses the
        # expensive image + audio steps.
        if db.is_step_done(job_id, scene_no, "subtitle_v3"):
            subtitle_path = Path(db.get_step_path(job_id, scene_no, "subtitle_v3"))
            logger.info(f"{tag} subtitle: already done")
        else:
            subtitle_path = paths.subtitle_path(scene_no)
            generate_hormozi_ass(
                audio_path=str(raw_audio),
                output_ass_path=str(subtitle_path),
                scene_text=str(scene.scene_text or ""),
                accent_color=config.get("video", {}).get("subtitle_color", "&H0000D7FF"),
                hook_text=hook_text if scene_no == 1 else "",
                emphasis_words=getattr(scene, "emphasis_words", []),
            )
            db.mark_step_done(job_id, scene_no, "subtitle_v3", str(subtitle_path))
            logger.info(f"{tag} subtitle saved")

        # ── Step 4: Silent motion video ───────────────────────────────────────
        if db.is_step_done(job_id, scene_no, "silent_video_v3"):
            silent_video = Path(db.get_step_path(job_id, scene_no, "silent_video_v3"))
            logger.info(f"{tag} silent_video: already done")
        else:
            video_cfg = config["video"]
            fps = int(video_cfg.get("fps", 30))
            supersample = float(video_cfg.get("supersample", 2.0))
            scene_tail_pad = max(0.25, float(video_cfg.get("scene_tail_pad", 0.65)))
            render_duration = audio_duration + scene_tail_pad
            frames = max(2, int(render_duration * fps))
            energy = getattr(scene, "scene_energy", "medium")

            # Stronger 3-second hook: scene 1 always opens with an aggressive
            # push-in + white-flash impact, regardless of its energy tag.
            hook_boost = bool(video_cfg.get("hook_boost", True))
            force_motion = "fast_push_in" if (scene_no == 1 and hook_boost) else ""
            motion = select_motion(scene_no, frames, fps, energy=energy,
                                   ss=supersample, force=force_motion)

            # Per-mood cinematic grade (same mood groups as the music library)
            mood = resolve_mood(channel_name, config.get("pipeline", {}).get("music_mood", ""))
            grade = MOOD_GRADES.get(mood, "")
            # White-flash impact: scene-1 hook open + maximum-energy scene cuts
            flash_in = bool(video_cfg.get("flash_cuts", True)) and (
                (scene_no == 1 and hook_boost)
                or (scene_no > 1 and _normalize_energy(energy) == "maximum")
            )

            fonts_dir = config.get("pipeline", {}).get("fonts_dir", "assets/fonts")
            silent_video = paths.silent_video_path(scene_no)
            await render_motion_video(
                image_path=str(image_path),
                duration=render_duration,
                zoom_expr=motion["zoom"],
                x_expr=motion["x"],
                y_expr=motion["y"],
                ass_path=str(subtitle_path),
                fps=fps,
                output_path=str(silent_video),
                quality_preset=video_cfg.get("quality_preset", "fast"),
                use_gpu=bool(video_cfg.get("use_gpu", False)),
                crf=int(video_cfg.get("crf", 16)),
                supersample=supersample,
                fonts_dir=fonts_dir,
                grade=grade,
                flash_in=flash_in,
                finish=bool(video_cfg.get("cinematic_finish", True)),
                overlay_path=(getattr(scene, "graphic", None) or {}).get("path", ""),
            )
            db.mark_step_done(job_id, scene_no, "silent_video_v3", str(silent_video))
            logger.info(
                f"{tag} silent video rendered ({motion['desc']}, {mood}, "
                f"{audio_duration:.2f}s voice + {scene_tail_pad:.2f}s tail)"
            )

        # ── Step 5: Mux audio + video ─────────────────────────────────────────
        if db.is_step_done(job_id, scene_no, "done_v3"):
            final_scene = Path(db.get_step_path(job_id, scene_no, "done_v3"))
            logger.info(f"{tag} mux: already done")
        else:
            final_scene = paths.scene_video_path(scene_no)
            voice_gain = float(config.get("kokoro", {}).get("voice_gain", 1.0))
            await mux_audio_video(
                video_path=str(silent_video),
                audio_path=str(raw_audio),
                output_path=str(final_scene),
                voice_gain=voice_gain,
                tone=getattr(scene, "voice_tone", "neutral"),
            )
            db.mark_step_done(job_id, scene_no, "done_v3", str(final_scene))
            logger.info(f"{tag} COMPLETE → {final_scene.name}")

            # The silent render is dead weight once it is muxed (~25MB each,
            # 16 per video). Safe on resume: done_v3 short-circuits step 5, so
            # the deleted path is never read back.
            if not config.get("pipeline", {}).get("keep_intermediates", False):
                purge(silent_video, f"{tag} silent render")

        if progress is not None and progress_task is not None:
            progress.advance(progress_task)

        return final_scene
