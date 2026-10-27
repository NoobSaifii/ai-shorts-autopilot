import os
import logging
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger("pipeline.uploaders.youtube")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

class YouTubeUploader:
    def __init__(self, client_secrets_file: str = "client_secrets.json", token_file: str = None):
        self.client_secrets_file = client_secrets_file
        self.token_file = token_file or "youtube_credentials.json"
        self.creds = None
        self._authenticate()

    def _authenticate(self):
        if os.path.exists(self.token_file):
            self.creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
        
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"Could not refresh token, re-authenticating: {e}")
                    self.creds = None
            
            if not self.creds:
                if not os.path.exists(self.client_secrets_file):
                    logger.error(f"Missing {self.client_secrets_file}. Cannot upload to YouTube.")
                    return
                
                flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, SCOPES)
                # This will open a browser window for the user to login. Only happens once.
                self.creds = flow.run_local_server(port=0)
            
            with open(self.token_file, 'w') as token:
                token.write(self.creds.to_json())

    def _set_thumbnail(self, youtube, video_id: str, thumbnail_path: str):
        """Best-effort custom thumbnail. Needs a verified channel — if not
        verified the API errors, which we swallow so the upload still counts."""
        if not thumbnail_path or not os.path.exists(thumbnail_path):
            return
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            logger.info(f"YouTube custom thumbnail set ✓ ({os.path.basename(thumbnail_path)})")
        except Exception as e:
            logger.warning(
                f"YouTube thumbnail not set (channel may be unverified): {e}"
            )

    def upload_video(self, video_path: str, title: str, description: str, tags: list,
                     max_attempts: int = 3, thumbnail_path: str = "") -> bool:
        if not self.creds:
            logger.error("Not authenticated with YouTube.")
            return False

        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return False

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                logger.info(f"YouTube retry attempt {attempt}/{max_attempts}...")
            try:
                youtube = build("youtube", "v3", credentials=self.creds)

                clean_tags = [t.strip('#') for t in tags]
                body = {
                    "snippet": {
                        "title": title[:100],
                        "description": description[:5000],
                        "tags": clean_tags,
                        "categoryId": "24",
                    },
                    "status": {
                        "privacyStatus": "public",
                        "selfDeclaredMadeForKids": False,
                    }
                }

                media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
                request = youtube.videos().insert(
                    part="snippet,status",
                    body=body,
                    media_body=media
                )

                logger.info(f"Uploading to YouTube Shorts: {title}...")
                response = request.execute()
                video_id = response.get("id")
                logger.info(f"YouTube Upload Successful! Video ID: {video_id}")

                # Custom thumbnail (best-effort — never fails the upload)
                if video_id and thumbnail_path:
                    self._set_thumbnail(youtube, video_id, thumbnail_path)
                return True

            except Exception as e:
                logger.warning(f"YouTube upload attempt {attempt} failed: {e}")

        logger.error(f"YouTube upload failed after {max_attempts} attempts")
        return False

