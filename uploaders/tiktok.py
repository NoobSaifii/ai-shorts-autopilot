import logging
import os
import subprocess
import time
import uuid
import requests

from utils.tiktok_auth import get_valid_tiktok_access_token

logger = logging.getLogger("pipeline.uploaders.tiktok")

TIKTOK_INIT_URL   = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

# TikTok Content Posting API only supports single-chunk FILE_UPLOAD.
# chunk_size must equal video_size, and video_size must be <= 64 MB.
# Videos larger than this are re-encoded at a lower bitrate before upload.
_MAX_SIZE_BYTES = 64 * 1024 * 1024   # 64 MB hard limit
_TK_TARGET_MB   = 58                  # re-encode target (headroom below 64 MB)


class TikTokUploader:
    def __init__(self, channel_name: str = "", sheet_id: str = "", sa_file: str = "", **kwargs):
        self.channel_name = channel_name
        self.sheet_id = sheet_id
        self.sa_file = sa_file

    def _compress(self, video_path: str) -> str | None:
        """Re-encode video to _TK_TARGET_MB so it fits in a single TikTok chunk."""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, check=True,
            )
            duration = float(result.stdout.strip())
        except Exception as e:
            logger.error(f"TikTok compress: ffprobe failed: {e}")
            return None

        target_bits   = _TK_TARGET_MB * 1024 * 1024 * 8
        audio_br      = 96_000
        video_br      = max(int((target_bits / duration) * 0.90) - audio_br, 500_000)

        tmp = os.path.join(os.path.dirname(video_path),
                           f"_tk_{uuid.uuid4().hex[:8]}.mp4")
        logger.info(f"TikTok compress: {os.path.getsize(video_path)//1024//1024}MB → "
                    f"target {_TK_TARGET_MB}MB ({video_br//1000}k vbr, {duration:.0f}s)...")
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path,
                "-c:v", "libx264", "-preset", "veryfast",
                "-b:v", str(video_br), "-maxrate", str(int(video_br * 1.2)),
                "-bufsize", str(video_br * 2),
                "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
                tmp,
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out_mb = os.path.getsize(tmp) / (1024 * 1024)
            logger.info(f"TikTok compress done: {out_mb:.1f}MB")
            return tmp
        except Exception as e:
            logger.error(f"TikTok compress: ffmpeg failed: {e}")
            if os.path.exists(tmp):
                os.remove(tmp)
            return None

    def upload_video(self, video_path: str, title: str, tags: list,
                     video_url: str = "", **kwargs) -> bool:
        """Upload a video to TikTok via FILE_UPLOAD (single chunk, ≤ 64 MB).

        video_url: reserved for future PULL_FROM_URL support once the TikTok
                   developer app is audited and a verified domain is configured.
                   Currently unused — TikTok requires domain ownership verification.
        """
        if not os.path.exists(video_path):
            logger.error(f"TikTok video file not found: {video_path}")
            return False

        access_token = get_valid_tiktok_access_token(self.channel_name, self.sheet_id, self.sa_file)
        if not access_token:
            return False

        caption = title
        if tags:
            hashtag_str = " ".join([f"#{t.replace(' ', '')}" for t in tags])
            caption = f"{title} {hashtag_str}"[:150]

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        # Compress if > 64 MB (TikTok single-chunk limit)
        upload_path = video_path
        compressed  = None
        if os.path.getsize(video_path) > _MAX_SIZE_BYTES:
            compressed = self._compress(video_path)
            if not compressed:
                logger.error("TikTok: compression failed, cannot upload file > 64 MB")
                return False
            upload_path = compressed

        file_size = os.path.getsize(upload_path)
        logger.info(f"Initializing TikTok upload ({file_size//1024//1024}MB, single chunk)...")

        init_payload = {
            "post_info": {
                "title": caption,
                "privacy_level": "SELF_ONLY",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1
            }
        }

        try:
            r = requests.post(TIKTOK_INIT_URL, json=init_payload, headers=headers)
            init_data = r.json()
        except Exception as e:
            logger.error(f"TikTok init request failed: {e}")
            return False
        finally:
            pass  # compressed cleanup happens after upload attempt

        if init_data.get("error", {}).get("code", "ok") != "ok":
            logger.error(f"TikTok init API error: {init_data}")
            if compressed and os.path.exists(compressed):
                os.remove(compressed)
            return False

        data_body  = init_data.get("data", {})
        publish_id = data_body.get("publish_id")
        upload_url = data_body.get("upload_url")

        if not publish_id or not upload_url:
            logger.error(f"TikTok init missing publish_id/upload_url: {init_data}")
            if compressed and os.path.exists(compressed):
                os.remove(compressed)
            return False

        logger.info("Uploading video file to TikTok...")
        try:
            with open(upload_path, "rb") as f:
                data = f.read()
            up_res = requests.put(
                upload_url, data=data,
                headers={
                    "Content-Range": f"bytes 0-{file_size-1}/{file_size}",
                    "Content-Type": "video/mp4",
                },
                timeout=180,
            )
            if up_res.status_code not in (200, 201, 206):
                logger.error(f"TikTok file upload failed ({up_res.status_code}): {up_res.text[:200]}")
                return False
            logger.info("TikTok file upload OK")
        except Exception as e:
            logger.error(f"TikTok file upload exception: {e}")
            return False
        finally:
            if compressed and os.path.exists(compressed):
                try:
                    os.remove(compressed)
                except OSError:
                    pass

        # Poll for completion
        logger.info("Polling TikTok publish status...")
        poll_payload = {"publish_id": publish_id}
        for _ in range(20):
            time.sleep(5)
            try:
                stat_res  = requests.post(TIKTOK_STATUS_URL, json=poll_payload, headers=headers)
                stat_data = stat_res.json()
                status    = stat_data.get("data", {}).get("status")
                if status == "PUBLISH_COMPLETE":
                    logger.info("TikTok Upload Successful!")
                    return True
                elif status == "FAILED":
                    logger.error(f"TikTok processing failed: {stat_data}")
                    return False
            except Exception as e:
                logger.warning(f"TikTok status poll exception: {e}")

        logger.error("TikTok upload timed out waiting for PUBLISH_COMPLETE.")
        return False
