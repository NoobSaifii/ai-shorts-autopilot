import asyncio
import json
import logging
import re
from pathlib import Path

from modules.audio_assets import (
    build_director_sfx_timeline,
    build_random_sfx_timeline,
    pick_music,
    resolve_mood,
)
from modules.image_gen import ImageGenerator
from modules.motion_graphics import render_graphics
from modules.script_gen import generate_script
from modules.topics import TopicRow
from modules.tts import KokoroClient
from modules.video import (
    add_background_music,
    ass_color_to_rgb_hex,
    enforce_length_constraint,
    get_video_duration,
)
from pipeline.merger import merge_scenes
from pipeline.scene_processor import process_scene
from utils.database import Database
from utils.disk import log_free, purge
from utils.paths import ProjectPaths

logger = logging.getLogger("pipeline.orchestrator")


def _scene_file_no(path: Path) -> int:
    m = re.search(r"_scene_(\d+)_", path.name)
    return int(m.group(1)) if m else 10**9


async def run_topic(
    topic_row: TopicRow,
    config: dict,
    db: Database,
    topics_manager,
    sheet_name: str = "Sheet1",
    channel_name: str = "Restricted Lore",
    progress=None,
) -> str:
    topic = topic_row.topic
    logger.info(f"━━━ Starting topic: {topic}")

    if db.is_job_completed(topic):
        logger.info(f"Topic already completed — skipping: {topic}")
        return ""

    job_id = db.get_or_create_job(topic, topic_row.series_name, topic_row.episode_no)
    logger.info(f"Job ID: {job_id}")

    # ── Script Generation ─────────────────────────────────────────────────────
    logger.info("Generating script via Gemini...")
    script = await generate_script(
        series_name=topic_row.series_name,
        episode_no=topic_row.episode_no,
        topic=topic,
        channel=channel_name,
        api_key=config["gemini"]["api_key"],
        model=config["gemini"]["model"],
        temperature=config["gemini"]["temperature"],
        top_p=config["gemini"]["top_p"],
        top_k=config["gemini"]["top_k"],
        models=config["gemini"].get("models"),
        llm_config=config.get("llm"),
    )
    logger.info(f"Script ready: '{script.title}' — {len(script.scenes)} scenes")

    db.set_job_title(job_id, script.title)

    # ── Folder Setup ──────────────────────────────────────────────────────────
    channel_output_root = str(Path(config["pipeline"]["output_root"]) / channel_name)
    paths = ProjectPaths(channel_output_root, script.title)
    paths.create_all()
    logger.info(f"Project folder: {paths.root}")
    keep_intermediates = bool(config.get("pipeline", {}).get("keep_intermediates", False))
    log_free(f"start of '{script.title}'", paths.root)

    # ── Parallel Scene Processing ─────────────────────────────────────────────
    max_parallel = int(config["pipeline"].get("max_parallel_scenes", 4))
    semaphore = asyncio.Semaphore(max_parallel)

    image_gen = ImageGenerator(config["image_providers"])
    tts_client = KokoroClient(config["kokoro"]["base_url"])

    progress_task = None
    if progress:
        progress_task = progress.add_task(
            f"[cyan]{script.title[:40]}",
            total=len(script.scenes),
        )

    # Motion-graphic cards render before the scenes so each scene's render can
    # overlay its card in the same encode.
    video_cfg = config.get("video", {})
    if video_cfg.get("motion_graphics", False):
        cards = await render_graphics(
            script.scenes,
            "#" + ass_color_to_rgb_hex(video_cfg.get("subtitle_color", "&H0000D7FF"))[2:],
            Path(paths.root) / "graphics",
        )
        for s in script.scenes:
            if s.scene_no in cards:
                s.graphic["path"] = cards[s.scene_no]

    tasks = [
        process_scene(
            scene=s,
            job_id=job_id,
            config=config,
            db=db,
            paths=paths,
            image_gen=image_gen,
            tts_client=tts_client,
            semaphore=semaphore,
            channel_name=channel_name,
            hook_text=script.hook_text,
            progress=progress,
            progress_task=progress_task,
        )
        for s in script.scenes
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    failed = [r for r in results if isinstance(r, Exception)]
    if failed:
        for e in failed:
            logger.error(f"Scene failed: {e}")
        db.mark_job_failed(job_id, str(failed[0]))
        raise RuntimeError(f"{len(failed)}/{len(script.scenes)} scenes failed for '{script.title}'")

    logger.info(f"All {len(script.scenes)} scenes complete. Merging...")

    # ── Merge Scenes (hard cuts by default → concat stream-copy, no re-encode) ─
    transition_duration = float(config["video"].get("transition_duration", 0) or 0)
    final_video = paths.final_video_path()
    merge_scenes(
        scene_dir=str(paths.scene_video),
        output_path=str(final_video),
        fps=int(config["video"].get("fps", 30)),
        transition_duration=transition_duration,
    )

    # ── Final Audio Mix: ducked music + SFX timeline + -14 LUFS master ───────
    pipeline_cfg = config.get("pipeline", {})

    mood = resolve_mood(channel_name, pipeline_cfg.get("music_mood", ""))
    music_path = pick_music(
        mood=mood,
        music_dir=pipeline_cfg.get("music_dir", "assets/music"),
        fallback_path=pipeline_cfg.get("music_path", ""),
        seed=script.title,
    )

    # Real per-scene durations (ffprobe) + script energies drive the SFX events
    scene_files = sorted(Path(paths.scene_video).glob("*.mp4"), key=_scene_file_no)
    scene_durations = [await get_video_duration(str(p)) for p in scene_files]
    if transition_duration > 0 and len(scene_durations) > 1:
        # xfade overlaps shift later scenes earlier on the master timeline
        scene_durations = [
            max(d - transition_duration, 0.1) for d in scene_durations[:-1]
        ] + [scene_durations[-1]]

    ordered_scenes = sorted(script.scenes, key=lambda s: s.scene_no)
    sfx_dir = pipeline_cfg.get("sfx_dir", "assets/sfx")

    # One random SFX per scene, drawn from the assets/sfx/ pool and placed at
    # each scene cut (deterministic per video via the title seed).
    scene_starts = []
    acc = 0.0
    for d in scene_durations:
        scene_starts.append(acc)
        acc += max(d, 0.0)

    sfx_events = build_random_sfx_timeline(
        scene_starts=scene_starts,
        sfx_dir=sfx_dir,
        seed=script.title,
    )
    # A card's entrance gets a whoosh in place of that cut's random hit.
    card_sfx = ["whoosh" if (s.graphic or {}).get("path") else "" for s in ordered_scenes]
    card_events = build_director_sfx_timeline(
        scene_starts=scene_starts, scene_sfx=card_sfx, sfx_dir=sfx_dir,
        seed=script.title, min_spacing=0.0,
    )
    if card_events:  # random events are one per scene, in scene order
        sfx_events = [e for i, e in enumerate(sfx_events)
                      if i >= len(card_sfx) or not card_sfx[i]] + card_events

    # Burned-in pro-editing layer: animated progress bar (channel accent) +
    # subtle channel watermark. Music swells need the exact mix duration.
    mix_duration = await get_video_duration(str(final_video))
    accent = video_cfg.get("subtitle_color", "&H0000D7FF")
    progress_color = (
        ass_color_to_rgb_hex(accent) if bool(video_cfg.get("progress_bar", True)) else ""
    )
    watermark = channel_name.upper() if bool(video_cfg.get("watermark", True)) else ""

    bgm_path = paths.final_bgm_path()
    await add_background_music(
        video_path=str(final_video),
        music_path=music_path,
        output_path=str(bgm_path),
        voice_volume=float(pipeline_cfg.get("voice_volume", 1.0)),
        music_volume=float(pipeline_cfg.get("music_volume", 0.15)),
        sfx_events=sfx_events,
        duration=mix_duration,
        progress_bar_color=progress_color,
        watermark_text=watermark,
        fonts_dir=pipeline_cfg.get("fonts_dir", "assets/fonts"),
    )
    final_output = str(bgm_path)
    logger.info(f"Final mix (music: {'yes' if music_path else 'no'}, "
                f"sfx: {len(sfx_events)}, bar: {'on' if progress_color else 'off'}, "
                f"wm: {'on' if watermark else 'off'}) → {bgm_path}")

    # ── Length Constraint (safety net — scripts are word-budgeted) ───────────
    # full_path  = original length (kept on disk / archive only)
    # shorts_path = ≤ target — uploaded to YouTube, Instagram and Facebook.
    target_max = float(pipeline_cfg.get("target_max_duration", 175.0))
    full_path = final_output
    duration = await get_video_duration(full_path)

    if duration > target_max:
        shorts_path = full_path.replace(".mp4", "_shorts.mp4")
        await enforce_length_constraint(full_path, target_max_duration=target_max, output_path=shorts_path)
        logger.info(f"Shorts version created ({duration:.1f}s → {target_max:.0f}s): {shorts_path}")
    else:
        shorts_path = full_path  # already within limit, same file for all platforms

    # ── Custom thumbnail (dedicated generated image + pro design) ────────────
    thumbnail_yt = ""
    thumbnail_v = ""
    if bool(config.get("thumbnails", True)):
        try:
            from modules.thumbnail import generate_thumbnails
            from modules.image_gen import AllProvidersExhausted

            final_dir = Path(full_path).parent
            thumb_src = final_dir / "thumbnail_src.jpg"
            got_src = False

            tprompt = (getattr(script, "thumbnail_prompt", "") or "").strip()
            if tprompt:
                full_tp = (
                    f"{tprompt} bold dramatic scroll-stopping thumbnail, vivid high "
                    "contrast, no text, no watermark, no logo"
                )
                try:
                    img_bytes = await image_gen.generate_image(
                        title=paths.title, scene_no=0, prompt=full_tp,
                        width=config["video"]["width"], height=config["video"]["height"],
                    )
                    thumb_src.write_bytes(img_bytes)
                    got_src = True
                except AllProvidersExhausted:
                    logger.warning("Thumbnail image gen exhausted — falling back to scene-1 image")

            if not got_src and ordered_scenes:
                s1 = db.get_step_path(job_id, ordered_scenes[0].scene_no, "image")
                if s1 and Path(s1).is_file():
                    thumb_src = Path(s1)
                    got_src = True

            if got_src:
                thumbs = generate_thumbnails(
                    src_path=str(thumb_src),
                    out_dir=str(Path(full_path).parent),
                    text=(getattr(script, "thumbnail_text", "") or script.hook_text
                          or getattr(script, "viral_title", script.title)),
                    keyword=getattr(script, "thumbnail_keyword", ""),
                    accent_color=config.get("video", {}).get("subtitle_color", ""),
                    channel_name=channel_name,
                )
                thumbnail_yt = thumbs.get("thumbnail_yt", "")
                thumbnail_v = thumbs.get("thumbnail_v", "")
                logger.info(f"Thumbnails ready (yt={'y' if thumbnail_yt else 'n'}, "
                            f"v={'y' if thumbnail_v else 'n'})")
        except Exception as e:
            logger.warning(f"Thumbnail step failed (non-fatal): {e}")

    metadata = {
        "title": script.title,
        "viral_title": getattr(script, "viral_title", script.title),
        "short_description": getattr(script, "short_description", ""),
        "hashtags": getattr(script, "hashtags", []),
        "hook_text": getattr(script, "hook_text", ""),
        "engagement_question": getattr(script, "engagement_question", ""),
        "thumbnail_yt": thumbnail_yt,
        "thumbnail_v": thumbnail_v,
        "duration_s": round(duration, 1),
        "full_path": full_path,
        "shorts_path": shorts_path,
    }

    metadata_path = Path(full_path).parent / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # ── Mark Done ─────────────────────────────────────────────────────────────
    # The video is fully made by this point. Marking the topic done is bookkeeping
    # (a Google Sheets network write, with its own retries). If it STILL fails, do
    # NOT throw away the finished video — log it and let the upload proceed; the DB
    # already records completion so it won't be regenerated.
    db.mark_job_completed(job_id)
    try:
        topics_manager.mark_done(topic, sheet_name=sheet_name)
    except Exception as e:
        logger.error(
            f"mark_done failed after retries — video IS made, uploading anyway "
            f"(topic may stay 'Pending' in the sheet): {e}"
        )

    # Everything outside final/ is scratch now. Deleting it only here — after
    # mark_job_completed — keeps resume safe: a re-entry short-circuits on
    # is_job_completed and never looks for the deleted scene files.
    if not keep_intermediates:
        for d in (paths.images, paths.audio, paths.silent_video, paths.scene_video):
            purge(d, f"{script.title}/{d.name}")
        purge(final_video, "pre-mix merge output")
        log_free(f"end of '{script.title}'", paths.final)

    logger.info(f"[DONE] {script.title}")
    logger.info(f"  Full video   -> {full_path}")
    logger.info(f"  Shorts video -> {shorts_path}")

    return full_path
