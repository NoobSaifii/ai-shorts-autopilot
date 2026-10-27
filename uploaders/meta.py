import logging
import os
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

logger = logging.getLogger("pipeline.uploaders.meta")

UPLOAD_TIMEOUT = (20, 300)
GRAPH_TIMEOUT = (20, 120)
REQUEST_HEADERS = {"User-Agent": "ai-video-pipeline/1.0"}


class MetaUploader:
    def __init__(self, fb_page_id: str, ig_user_id: str, access_token: str):
        self.fb_page_id = fb_page_id
        self.ig_user_id = ig_user_id
        self.access_token = access_token
        self.graph_url = "https://graph.facebook.com/v19.0"
        self.last_ig_public_url: str = ""  # set after each IG upload; reusable by TikTok

    def _response_text(self, response: requests.Response) -> str:
        try:
            return str(response.json())[:500]
        except ValueError:
            return response.text[:500]

    def _prepare_video_for_instagram(self, video_path: str):
        """Upload an IG-ready video to a public host. Returns (video_url, path_used)."""
        if not os.path.exists(video_path):
            logger.error(f"Instagram video file not found: {video_path}")
            return None, None

        candidates, cleanup_paths = self._instagram_upload_candidates(video_path)
        try:
            for upload_target in candidates:
                size_mb = os.path.getsize(upload_target) / (1024 * 1024)
                logger.info(
                    f"Preparing Instagram public URL from {Path(upload_target).name} "
                    f"({size_mb:.1f}MB)"
                )

                video_url = self._upload_to_s3_host(upload_target)
                if video_url:
                    return video_url, upload_target

                video_url = self._upload_to_temp_host(upload_target)
                if video_url:
                    return video_url, upload_target
        finally:
            for cleanup_path in cleanup_paths:
                try:
                    if os.path.exists(cleanup_path):
                        os.remove(cleanup_path)
                except OSError as exc:
                    logger.warning(f"Could not remove temp IG file {cleanup_path}: {exc}")

        return None, None

    def _instagram_upload_candidates(self, video_path: str) -> tuple[list[str], list[str]]:
        """Build smaller upload candidates so public temp hosts do not time out."""
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        temp_host_limit_mb = float(os.getenv("IG_TEMP_HOST_MAX_MB", "95"))
        raw_targets = os.getenv("IG_TEMP_TARGET_MB", "80,45")
        target_sizes: list[float] = []
        for item in raw_targets.split(","):
            try:
                target = float(item.strip())
            except ValueError:
                continue
            if target > 5:
                target_sizes.append(target)

        candidates: list[str] = []
        cleanup_paths: list[str] = []

        if self._s3_enabled():
            logger.info(f"Video size ({size_mb:.1f}MB) is ready for Instagram hosting (S3/R2).")
            return [video_path], []
            
        if size_mb <= temp_host_limit_mb:
            logger.info(f"Video size ({size_mb:.1f}MB) is ready for Instagram hosting (Temp).")
            candidates.append(video_path)
        else:
            logger.info(
                f"Video size ({size_mb:.1f}MB) is high for free temp hosts; "
                "creating smaller Instagram upload copies."
            )

        for target_mb in target_sizes:
            if size_mb <= target_mb * 0.95:
                continue
            tmp_path = self._compress_video_for_instagram(video_path, target_mb)
            if tmp_path:
                candidates.append(tmp_path)
                cleanup_paths.append(tmp_path)

        if not candidates:
            candidates.append(video_path)

        return candidates, cleanup_paths

    def _probe_duration(self, video_path: str) -> float:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return float(result.stdout.strip())
        except Exception as exc:
            logger.warning(f"Could not probe video duration for IG compression: {exc}")
            return 0.0

    def _compress_video_for_instagram(self, video_path: str, target_mb: float) -> str | None:
        duration = self._probe_duration(video_path)
        if duration <= 0:
            return None

        target_bits = target_mb * 1024 * 1024 * 8
        audio_bitrate = 96_000
        video_bitrate = max(int((target_bits / duration) * 0.88) - audio_bitrate, 650_000)
        maxrate = int(video_bitrate * 1.25)
        bufsize = int(video_bitrate * 2)
        source = Path(video_path)
        tmp_path = str(source.with_name(f"{source.stem}_ig_{int(target_mb)}mb_{uuid.uuid4().hex[:8]}.mp4"))

        logger.info(
            f"Creating Instagram temp copy <= {target_mb:.0f}MB "
            f"({video_bitrate // 1000}k video bitrate)..."
        )
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    video_path,
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-b:v",
                    str(video_bitrate),
                    "-maxrate",
                    str(maxrate),
                    "-bufsize",
                    str(bufsize),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "96k",
                    "-movflags",
                    "+faststart",
                    tmp_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            out_mb = os.path.getsize(tmp_path) / (1024 * 1024)
            logger.info(f"Instagram temp copy ready: {out_mb:.1f}MB")
            return tmp_path
        except Exception as exc:
            logger.warning(f"Instagram compression to {target_mb:.0f}MB failed: {exc}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return None

    def start_instagram_upload(self, video_path: str, caption: str, cover_url: str = "") -> str | None:
        """
        Phase 1: upload video to a public host and initialise an IG container.
        Returns creation_id immediately; finish_instagram_upload publishes it.
        cover_url (optional) = public image URL for a custom Reel cover.
        """
        if not self.ig_user_id or not self.access_token:
            logger.error("Missing Instagram ID or Access Token.")
            return None

        video_url, _ = self._prepare_video_for_instagram(video_path)
        if not video_url:
            logger.error("All Instagram public hosting providers failed.")
            return None

        self.last_ig_public_url = video_url
        logger.info(f"Temporary public URL: {video_url}")
        logger.info("Initializing Instagram Reel container...")

        init_url = f"{self.graph_url}/{self.ig_user_id}/media"
        payload = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": self.access_token,
        }
        if cover_url:
            payload["cover_url"] = cover_url
            logger.info("Using custom Instagram Reel cover.")
        try:
            resp = requests.post(init_url, data=payload, headers=REQUEST_HEADERS, timeout=GRAPH_TIMEOUT)
        except requests.RequestException as exc:
            logger.error(f"IG Init request failed: {exc}")
            return None
        if resp.status_code != 200:
            logger.error(f"IG Init failed ({resp.status_code}): {self._response_text(resp)}")
            return None

        creation_id = resp.json().get("id")
        logger.info(f"IG container created: {creation_id} - processing in background")
        return creation_id

    def finish_instagram_upload(self, creation_id: str) -> bool:
        """Poll until Meta finishes processing, then publish."""
        status_url = (
            f"{self.graph_url}/{creation_id}"
            f"?fields=status_code&access_token={self.access_token}"
        )
        deadline = time.monotonic() + int(os.getenv("IG_PROCESSING_TIMEOUT_SECONDS", "900"))
        while time.monotonic() < deadline:
            try:
                status_resp = requests.get(status_url, headers=REQUEST_HEADERS, timeout=(20, 60))
                status = status_resp.json().get("status_code")
            except (requests.RequestException, ValueError) as exc:
                logger.warning(f"IG status poll failed: {exc}")
                time.sleep(5)
                continue
            if status == "FINISHED":
                break
            if status == "ERROR":
                logger.error("IG Video processing failed on Meta's servers.")
                return False
            time.sleep(2)
        else:
            logger.error("IG Video processing timed out on Meta's servers.")
            return False

        logger.info("Publishing Instagram Reel...")
        pub_url = f"{self.graph_url}/{self.ig_user_id}/media_publish"
        try:
            pub_resp = requests.post(
                pub_url,
                data={"creation_id": creation_id, "access_token": self.access_token},
                headers=REQUEST_HEADERS,
                timeout=GRAPH_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.error(f"IG Publish request failed: {exc}")
            return False
        if pub_resp.status_code == 200:
            logger.info(f"Instagram Upload Successful! ID: {pub_resp.json().get('id')}")
            return True
        logger.error(f"IG Publish failed ({pub_resp.status_code}): {self._response_text(pub_resp)}")
        try:
            # Meta marks errors it won't recover from — retrying those just burns
            # ~9 runner minutes per channel (4 fresh uploads + backoff).
            self._ig_fatal = pub_resp.json().get("error", {}).get("is_transient") is False
        except ValueError:
            pass
        return False

    def upload_to_instagram_reels(self, video_path: str, caption: str, max_attempts: int = 4,
                                  cover_path: str = "") -> bool:
        """
        Full Instagram upload with retry. Each attempt rebuilds a public URL and
        re-initialises the Meta container, because Meta will not accept local files.
        cover_path (optional) = local thumbnail image; hosted once for cover_url.
        """
        # Host the custom cover once (best-effort) and reuse across attempts.
        cover_url = ""
        if cover_path and os.path.exists(cover_path):
            try:
                if self._s3_enabled():
                    cover_url = self._upload_to_s3_host(cover_path) or ""
                if not cover_url:
                    cover_url = self._upload_to_temp_host(cover_path) or ""
                    
                if cover_url:
                    logger.info(f"IG cover hosted: {cover_url}")
            except Exception as e:
                logger.warning(f"IG cover hosting failed (using default cover): {e}")

        self._ig_fatal = False
        for attempt in range(1, max_attempts + 1):
            if self._ig_fatal:
                logger.error("IG error is non-transient — skipping remaining retries")
                return False
            if attempt > 1:
                logger.info(f"IG retry attempt {attempt}/{max_attempts}...")
            creation_id = self.start_instagram_upload(video_path, caption, cover_url=cover_url)
            if not creation_id:
                logger.warning(f"IG init failed on attempt {attempt}")
                time.sleep(min(30 * attempt, 90))
                continue
            result = self.finish_instagram_upload(creation_id)
            if result:
                return True
            logger.warning(f"IG processing failed on attempt {attempt} - will retry with fresh upload")
            time.sleep(min(30 * attempt, 90))
        logger.error(f"Instagram upload failed after {max_attempts} attempts")
        return False

    def _s3_enabled(self) -> bool:
        return all(
            os.getenv(name)
            for name in (
                "IG_S3_ENDPOINT_URL",
                "IG_S3_BUCKET",
                "IG_S3_ACCESS_KEY_ID",
                "IG_S3_SECRET_ACCESS_KEY",
            )
        )

    def _upload_to_s3_host(self, video_path: str) -> str | None:
        """Optional durable hosting for IG URLs via S3-compatible storage such as Cloudflare R2."""
        if not self._s3_enabled():
            return None

        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            logger.warning("IG_S3_* secrets are set, but boto3 is not installed.")
            return None

        bucket = os.environ["IG_S3_BUCKET"]
        endpoint = os.environ["IG_S3_ENDPOINT_URL"]
        region = os.getenv("IG_S3_REGION", "auto")
        prefix = os.getenv("IG_S3_PREFIX", "instagram").strip("/")
        public_base = os.getenv("IG_S3_PUBLIC_BASE_URL", "").rstrip("/")
        key = f"{prefix}/{uuid.uuid4().hex}-{Path(video_path).name}"

        try:
            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=os.environ["IG_S3_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["IG_S3_SECRET_ACCESS_KEY"],
                region_name=region,
                config=Config(signature_version="s3v4"),
            )
            # Keep the bucket tiny (free tier): delete objects from previous runs.
            # IG only needs the URL alive for a few minutes, so anything older than
            # a few hours is safe to remove. Best-effort — never blocks the upload.
            self._s3_prune_old(client, bucket, prefix)
            logger.info(f"Uploading Instagram video to durable S3/R2 host: s3://{bucket}/{key}")
            client.upload_file(video_path, bucket, key, ExtraArgs={"ContentType": "video/mp4"})
            if public_base:
                return f"{public_base}/{quote(key)}"
            expires = int(os.getenv("IG_S3_PRESIGN_SECONDS", "21600"))
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires,
            )
        except Exception as exc:
            logger.warning(f"S3/R2 Instagram hosting failed: {exc}")
            return None

    def _s3_prune_old(self, client, bucket: str, prefix: str, max_age_hours: float = 6.0):
        """Best-effort: delete stale objects under prefix so storage stays in the
        free tier without needing a bucket lifecycle rule (which an Object-scoped
        token can't set). Uses only list+delete, which the R2 token allows.
        Never raises — a cleanup hiccup must not block the actual upload."""
        try:
            from datetime import datetime, timezone, timedelta

            cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            stale = []
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/"):
                for obj in page.get("Contents", []):
                    if obj.get("LastModified") and obj["LastModified"] < cutoff:
                        stale.append({"Key": obj["Key"]})
            if not stale:
                return
            for i in range(0, len(stale), 1000):
                client.delete_objects(
                    Bucket=bucket, Delete={"Objects": stale[i:i + 1000], "Quiet": True}
                )
            logger.info(f"R2 cleanup: removed {len(stale)} stale Instagram object(s)")
        except Exception as exc:
            logger.debug(f"R2 cleanup skipped (non-fatal): {exc}")

    def _upload_to_temp_host(self, video_path: str) -> str | None:
        """Try multiple free hosts to get a public video URL for Instagram."""

        try:
            logger.info("Trying litterbox.catbox.moe...")
            with open(video_path, "rb") as f:
                r = requests.post(
                    "https://litterbox.catbox.moe/resources/internals/api.php",
                    data={"reqtype": "fileupload", "time": "72h"},
                    files={"fileToUpload": f},
                    headers=REQUEST_HEADERS,
                    timeout=UPLOAD_TIMEOUT,
                )
            if r.status_code == 200 and r.text.strip().startswith("http"):
                logger.info(f"litterbox OK: {r.text.strip()}")
                return r.text.strip()
            logger.warning(f"litterbox failed ({r.status_code}): {r.text[:100]}")
        except Exception as e:
            logger.warning(f"litterbox exception: {e}")

        try:
            logger.info("Trying 0x0.st...")
            with open(video_path, "rb") as f:
                r = requests.post(
                    "https://0x0.st",
                    files={"file": (Path(video_path).name, f, "video/mp4")},
                    headers=REQUEST_HEADERS,
                    timeout=UPLOAD_TIMEOUT,
                )
            if r.status_code == 200 and r.text.strip().startswith("http"):
                logger.info(f"0x0.st OK: {r.text.strip()}")
                return r.text.strip()
            logger.warning(f"0x0.st failed ({r.status_code}): {r.text[:100]}")
        except Exception as e:
            logger.warning(f"0x0.st exception: {e}")

        try:
            logger.info("Trying temp.sh...")
            filename = quote(Path(video_path).name)
            with open(video_path, "rb") as f:
                r = requests.put(
                    f"https://temp.sh/upload/{filename}",
                    data=f,
                    headers={**REQUEST_HEADERS, "Content-Type": "video/mp4"},
                    timeout=UPLOAD_TIMEOUT,
                )
            if r.status_code == 200 and r.text.strip().startswith("http"):
                logger.info(f"temp.sh OK: {r.text.strip()}")
                return r.text.strip()
            logger.warning(f"temp.sh failed ({r.status_code}): {r.text[:100]}")
        except Exception as e:
            logger.warning(f"temp.sh exception: {e}")

        try:
            logger.info("Trying uguu.se...")
            with open(video_path, "rb") as f:
                r = requests.post(
                    "https://uguu.se/upload.php",
                    files={"files[]": (Path(video_path).name, f, "video/mp4")},
                    headers=REQUEST_HEADERS,
                    timeout=UPLOAD_TIMEOUT,
                )
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            url = (data.get("files") or [{}])[0].get("url")
            if r.status_code == 200 and url:
                logger.info(f"uguu.se OK: {url}")
                return url
            logger.warning(f"uguu.se failed ({r.status_code}): {r.text[:100]}")
        except Exception as e:
            logger.warning(f"uguu.se exception: {e}")

        try:
            logger.info("Trying pixeldrain.com...")
            with open(video_path, "rb") as f:
                r = requests.post(
                    "https://pixeldrain.com/api/file",
                    files={"file": (Path(video_path).name, f, "video/mp4")},
                    headers=REQUEST_HEADERS,
                    timeout=UPLOAD_TIMEOUT,
                )
            data = r.json()
            if r.status_code in (200, 201) and data.get("success") and data.get("id"):
                url = f"https://pixeldrain.com/api/file/{data['id']}?download"
                logger.info(f"pixeldrain OK: {url}")
                return url
            logger.warning(f"pixeldrain failed ({r.status_code}): {r.text[:100]}")
        except Exception as e:
            logger.warning(f"pixeldrain exception: {e}")

        userhash = os.getenv("CATBOX_USERHASH", "").strip()
        if userhash:
            try:
                logger.info("Trying catbox.moe...")
                with open(video_path, "rb") as f:
                    r = requests.post(
                        "https://catbox.moe/user/api.php",
                        data={"reqtype": "fileupload", "userhash": userhash},
                        files={"fileToUpload": f},
                        headers=REQUEST_HEADERS,
                        timeout=UPLOAD_TIMEOUT,
                    )
                if r.status_code == 200 and r.text.strip().startswith("http"):
                    logger.info(f"catbox.moe OK: {r.text.strip()}")
                    return r.text.strip()
                logger.warning(f"catbox.moe failed ({r.status_code}): {r.text[:100]}")
            except Exception as e:
                logger.warning(f"catbox.moe exception: {e}")

        return None

    def _set_facebook_thumbnail(self, video_id: str, thumbnail_path: str, page_access_token: str):
        """Best-effort custom Reel cover via POST /{video_id}/thumbnails.
        Needs pages_manage_engagement; failure is non-fatal (FB auto-thumb)."""
        if not video_id or not thumbnail_path or not os.path.exists(thumbnail_path):
            return
        try:
            url = f"{self.graph_url}/{video_id}/thumbnails"
            with open(thumbnail_path, "rb") as f:
                resp = requests.post(
                    url,
                    data={"is_preferred": "true", "access_token": page_access_token},
                    files={"source": (Path(thumbnail_path).name, f, "image/jpeg")},
                    headers=REQUEST_HEADERS,
                    timeout=GRAPH_TIMEOUT,
                )
            if resp.status_code == 200:
                logger.info("Facebook custom thumbnail set ✓")
            else:
                logger.warning(f"FB thumbnail not set ({resp.status_code}): {self._response_text(resp)}")
        except Exception as e:
            logger.warning(f"FB thumbnail error (non-fatal): {e}")

    def upload_to_facebook_reels(self, video_path: str, description: str, max_attempts: int = 3,
                                 thumbnail_path: str = "") -> bool:
        if not self.fb_page_id or not self.access_token:
            logger.error("Missing FB Page ID or Access Token.")
            return False

        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return False

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                logger.info(f"Facebook retry attempt {attempt}/{max_attempts}...")
            try:
                # 1. Get Page Access Token
                page_token_url = f"{self.graph_url}/{self.fb_page_id}?fields=access_token&access_token={self.access_token}"
                pt_resp = requests.get(page_token_url, headers=REQUEST_HEADERS, timeout=GRAPH_TIMEOUT)
                if pt_resp.status_code != 200 or 'access_token' not in pt_resp.json():
                    logger.error(f"Failed to get FB Page Access Token: {self._response_text(pt_resp)}")
                    return False
                page_access_token = pt_resp.json()['access_token']

                logger.info("Initializing Facebook Reel Upload...")
                init_url = f"{self.graph_url}/{self.fb_page_id}/video_reels"

                init_resp = requests.post(
                    init_url,
                    data={"upload_phase": "start", "access_token": page_access_token},
                    headers=REQUEST_HEADERS,
                    timeout=GRAPH_TIMEOUT,
                )
                if init_resp.status_code != 200:
                    logger.warning(
                        f"FB Init failed (attempt {attempt}, {init_resp.status_code}): "
                        f"{self._response_text(init_resp)}"
                    )
                    continue

                video_id = init_resp.json().get("video_id")
                upload_url = init_resp.json().get("upload_url")

                logger.info("Uploading video file to Facebook...")
                file_size = os.path.getsize(video_path)
                with open(video_path, "rb") as f:
                    upload_resp = requests.post(
                        upload_url,
                        headers={
                            **REQUEST_HEADERS,
                            "Authorization": f"OAuth {page_access_token}",
                            "offset": "0",
                            "file_size": str(file_size),
                        },
                        data=f,
                        timeout=UPLOAD_TIMEOUT,
                    )

                if upload_resp.status_code != 200:
                    logger.warning(
                        f"FB file upload failed (attempt {attempt}, {upload_resp.status_code}): "
                        f"{self._response_text(upload_resp)}"
                    )
                    continue

                logger.info("FB Video uploaded successfully. Publishing...")
                pub_resp = requests.post(
                    init_url,
                    data={
                        "upload_phase": "finish",
                        "video_id": video_id,
                        "video_state": "PUBLISHED",
                        "description": description,
                        "access_token": page_access_token,
                    },
                    headers=REQUEST_HEADERS,
                    timeout=GRAPH_TIMEOUT,
                )
                if pub_resp.status_code == 200:
                    logger.info("Facebook Reel Published! ✔️")
                    self._set_facebook_thumbnail(video_id, thumbnail_path, page_access_token)
                    return True
                logger.warning(
                    f"FB Publish failed (attempt {attempt}, {pub_resp.status_code}): "
                    f"{self._response_text(pub_resp)}"
                )

            except Exception as e:
                logger.warning(f"Facebook upload attempt {attempt} exception: {e}")

        logger.error(f"Facebook upload failed after {max_attempts} attempts")
        return False
