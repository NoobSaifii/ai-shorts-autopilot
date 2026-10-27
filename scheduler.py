import time
import schedule
import logging
import asyncio
from pathlib import Path

# Adjust imports based on the actual file structure
from uploaders.youtube import YouTubeUploader
from uploaders.tiktok import TikTokUploader
from uploaders.meta import MetaUploader
from pipeline.orchestrator import run_topic
from utils.database import Database
from modules.topics import TopicsManager
from modules.tts import ensure_kokoro_running
from main import load_config
import yaml
import json
import logging
import asyncio
from pathlib import Path

logger = logging.getLogger("pipeline.scheduler")

def get_channel_config(channel_name: str, config_path: str = "config.yaml"):
    config = load_config(config_path)
    for ch in config.get("channels", []):
        if ch["name"] == channel_name:
            return ch, config
    return None, config

async def run_generation_for_channel(channel_name: str):
    ch, config = get_channel_config(channel_name)
    if not ch:
        return None
        
    db = Database(config.get("db_path", "pipeline_jobs.db"))
    topics_manager = TopicsManager(
        config["topics_file"],
        sheet_id=config.get("google_sheet_id", ""),
        sa_file=config.get("google_sa_file", ""),
    )
    
    while True:
        topic_row = topics_manager.get_next_pending(sheet_name=ch["sheet"])
        if not topic_row:
            logger.warning(f"No pending topics for {channel_name}")
            return None
            
        if db.is_job_completed(topic_row.topic):
            logger.info(f"Topic '{topic_row.topic}' is marked completed in DB, skipping in scheduler...")
            topics_manager.mark_done(topic_row.topic, sheet_name=ch["sheet"])
            continue
            
        break

    # Apply overrides
    if "voice" in ch:
        config.setdefault("kokoro", {})["voice"] = ch["voice"]
    if "speed" in ch:
        config.setdefault("kokoro", {})["speed"] = float(ch["speed"])
    if "voice_gain" in ch:
        config.setdefault("kokoro", {})["voice_gain"] = float(ch["voice_gain"])
    if "music_path" in ch:
        config.setdefault("pipeline", {})["music_path"] = ch["music_path"]
    if "music_mood" in ch:
        config.setdefault("pipeline", {})["music_mood"] = ch["music_mood"]
    if "subtitle_color" in ch:
        config.setdefault("video", {})["subtitle_color"] = ch["subtitle_color"]
    # Per-channel only (always set, so it never leaks from the previous channel)
    config.setdefault("video", {})["motion_graphics"] = bool(ch.get("motion_graphics", False))
    config.setdefault("kokoro", {})["voice_ref"] = str(ch.get("voice_ref", ""))

    return await run_topic(
        topic_row=topic_row,
        config=config,
        db=db,
        topics_manager=topics_manager,
        sheet_name=ch["sheet"],
        channel_name=ch["name"],
        progress=None
    )

def job():
    logger.info("Starting scheduled video generation job...")
    
    # 0. Start Kokoro TTS
    # Just use the first channel's config to get kokoro settings since it's global
    ch, config = get_channel_config("")
    kokoro_cfg = config.get("kokoro", {})
    asyncio.run(
        ensure_kokoro_running(
            base_url=kokoro_cfg.get("base_url", "http://localhost:8002"),
            script_path=kokoro_cfg.get("script_path", ""),
            timeout=90,
        )
    )
    
    channels = config.get("channels", [])
    for channel in channels:
        channel_name = channel.get("name")
        upload_cfg = channel.get("upload", {})
        
        # Only process channels that have an upload configuration
        if not upload_cfg:
            logger.info(f"Skipping {channel_name} because it has no upload config.")
            continue
            
        logger.info(f"--- Processing Job for Channel: {channel_name} ---")
        
        # 1. Generate Video
        video_path = asyncio.run(run_generation_for_channel(channel_name))
        
        if not video_path or not Path(video_path).exists():
            logger.error(f"Video was not generated properly for {channel_name}. Skipping upload.")
            continue

        # 2. Read Metadata
        project_dir = Path(video_path).parent.parent
        metadata_path = project_dir / "metadata.json"
        if not metadata_path.exists():
            logger.error(f"Metadata file missing at {metadata_path}. Skipping upload.")
            continue
            
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
        title = metadata.get("viral_title", "Viral AI Video")
        description = metadata.get("short_description", "Enjoy this video!")
        tags = metadata.get("hashtags", ["#viral", "#shorts", "#fyp"])
        
        # Format a full description with hashtags for platforms that don't have a separate tags field
        hashtags_str = " ".join([t if t.startswith('#') else f"#{t}" for t in tags])
        full_description = f"{description}\n\n{hashtags_str}"
        
        youtube_token = f"youtube_credentials_{channel_name.replace(' ', '_')}.json"
        tiktok_cookies = f"tiktok_cookies_{channel_name.replace(' ', '_')}.txt"

        # 3. Upload to YouTube
        logger.info(f"Uploading to YouTube for {channel_name}...")
        try:
            yt = YouTubeUploader(token_file=youtube_token)
            yt.upload_video(video_path, title, full_description, tags)
        except Exception as e:
            logger.error(f"YouTube upload failed for {channel_name}: {e}")

        # 4. Upload to TikTok
        logger.info(f"Uploading to TikTok for {channel_name} via LDPlayer...")
        try:
            tk = TikTokUploader(channel_name=channel_name)
            tk.upload_video(video_path, title, tags)
        except Exception as e:
            logger.error(f"TikTok upload failed for {channel_name}: {e}")

        # 5. Upload to Facebook / Instagram
        logger.info(f"Uploading to Meta for {channel_name}...")
        try:
            meta = MetaUploader(
                fb_page_id=upload_cfg.get("fb_page_id", ""),
                ig_user_id=upload_cfg.get("ig_user_id", ""),
                access_token=upload_cfg.get("meta_access_token", "")
            )
            # Facebook
            meta.upload_to_facebook_reels(video_path, full_description)
            # Instagram
            meta.upload_to_instagram_reels(video_path, full_description)
        except Exception as e:
            logger.error(f"Meta upload failed for {channel_name}: {e}")

def start_scheduler(upload_time: str = "18:00"):
    logger.info(f"Scheduler started. Will upload daily at {upload_time}.")
    schedule.every().day.at(upload_time).do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Start the scheduler
    # start_scheduler("18:00")
    
    # For testing, run the job immediately
    logger.info("Test Mode: Running job now (dry-run style, will fail if no keys)")
    # job()
