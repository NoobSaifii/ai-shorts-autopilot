import asyncio
import json
import logging
from pathlib import Path
import argparse

from scheduler import get_channel_config, run_generation_for_channel
from modules.tts import ensure_kokoro_running
from uploaders.youtube import YouTubeUploader
from uploaders.tiktok import TikTokUploader
from uploaders.meta import MetaUploader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_now")

def run_now(target_channel: str):
    logger.info(f"Starting immediate generation and upload for: {target_channel}")
    
    ch, config = get_channel_config(target_channel)
    if not ch:
        logger.error(f"Channel '{target_channel}' not found in config.yaml")
        return

    upload_cfg = ch.get("upload", {})
    if not upload_cfg:
        logger.warning(f"No upload config found for {target_channel}. Only generating video.")

    kokoro_cfg = config.get("kokoro", {})
    asyncio.run(
        ensure_kokoro_running(
            base_url=kokoro_cfg.get("base_url", "http://localhost:8002"),
            script_path=kokoro_cfg.get("script_path", ""),
            timeout=90,
        )
    )
    
    # 1. Generate Video
    video_path = asyncio.run(run_generation_for_channel(target_channel))
    
    if not video_path or not Path(video_path).exists():
        logger.error("Video was not generated properly. Skipping upload.")
        return

    # 2. Read Metadata
    project_dir = Path(video_path).parent.parent
    metadata_path = project_dir / "metadata.json"
    if not metadata_path.exists():
        logger.error(f"Metadata file missing at {metadata_path}. Skipping upload.")
        return
        
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
        
    title = metadata.get("viral_title", "Viral AI Video")
    description = metadata.get("short_description", "Enjoy this video!")
    tags = metadata.get("hashtags", ["#viral", "#shorts", "#fyp"])
    
    hashtags_str = " ".join([t if t.startswith('#') else f"#{t}" for t in tags])
    full_description = f"{description}\n\n{hashtags_str}"
    
    youtube_token = f"youtube_credentials_{target_channel.replace(' ', '_')}.json"
    tiktok_cookies = f"tiktok_cookies_{target_channel.replace(' ', '_')}.txt"

    # 3. Upload to YouTube
    logger.info(f"Uploading to YouTube for {target_channel}...")
    try:
        yt = YouTubeUploader(token_file=youtube_token)
        yt.upload_video(video_path, title, full_description, tags)
    except Exception as e:
        logger.error(f"YouTube upload failed: {e}")

    # 4. Upload to TikTok
    logger.info(f"Uploading to TikTok for {target_channel} via LDPlayer...")
    try:
        tk = TikTokUploader(channel_name=target_channel)
        tk.upload_video(video_path, title, tags)
    except Exception as e:
        logger.error(f"TikTok upload failed: {e}")

    # 5. Upload to Meta
    if upload_cfg:
        logger.info(f"Uploading to Meta for {target_channel}...")
        try:
            meta = MetaUploader(
                fb_page_id=upload_cfg.get("fb_page_id", ""),
                ig_user_id=upload_cfg.get("ig_user_id", ""),
                access_token=upload_cfg.get("meta_access_token", "")
            )
            meta.upload_to_facebook_reels(video_path, full_description)
            meta.upload_to_instagram_reels(video_path, full_description)
        except Exception as e:
            logger.error(f"Meta upload failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", type=str, required=True, help="Name of the channel to process")
    args = parser.parse_args()
    run_now(args.channel)
