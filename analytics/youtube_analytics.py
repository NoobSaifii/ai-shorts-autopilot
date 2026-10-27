"""YouTube channel analytics using existing OAuth upload credentials."""
import logging
from pathlib import Path

logger = logging.getLogger("analytics.youtube")
BASE_DIR = Path(__file__).resolve().parent.parent


def _build_yt(channel_name: str):
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    cred_name = channel_name.replace(" ", "_")
    # Check analytics-specific creds first, then fallback to upload creds
    for fname in [f"youtube_analytics_{cred_name}.json", f"youtube_credentials_{cred_name}.json"]:
        p = BASE_DIR / fname
        if not p.exists():
            continue
        try:
            creds = Credentials.from_authorized_user_file(str(p))
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                p.write_text(creds.to_json())
            if creds.valid:
                return build("youtube", "v3", credentials=creds)
        except Exception as e:
            logger.debug(f"{fname} load failed: {e}")
    return None


def get_channel_stats(channel_name: str) -> dict:
    """Get total channel views, subscriber count, and uploads playlist ID."""
    yt = _build_yt(channel_name)
    if not yt:
        return {"views": 0, "subscribers": 0, "error": "no_credentials"}
    try:
        resp = yt.channels().list(part="statistics,contentDetails", mine=True).execute()
        items = resp.get("items", [])
        if not items:
            return {"views": 0, "subscribers": 0, "error": "channel_not_found"}
        s = items[0]["statistics"]
        return {
            "channel_id": items[0]["id"],
            "views": int(s.get("viewCount", 0)),
            "subscribers": int(s.get("subscriberCount", 0)),
            "video_count": int(s.get("videoCount", 0)),
            "uploads_playlist": items[0]["contentDetails"]["relatedPlaylists"]["uploads"],
        }
    except Exception as e:
        msg = str(e)
        logger.warning(f"YT channel stats failed for {channel_name}: {msg}")
        # youtube.upload scope may not allow channels.list — show helpful hint
        if "insufficientPermissions" in msg or "forbidden" in msg.lower():
            return {"views": 0, "subscribers": 0, "error": "needs_reauth", "hint": "Run setup_yt_analytics.py"}
        return {"views": 0, "subscribers": 0, "error": msg}


def get_recent_videos(channel_name: str, count: int = 10) -> list:
    """Return last N uploaded videos with view counts (ordered newest first)."""
    ch = get_channel_stats(channel_name)
    playlist_id = ch.get("uploads_playlist")
    if not playlist_id:
        return []

    yt = _build_yt(channel_name)
    if not yt:
        return []

    try:
        pl = yt.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=playlist_id,
            maxResults=count
        ).execute()

        video_ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        if not video_ids:
            return []

        vids = yt.videos().list(
            part="statistics,snippet",
            id=",".join(video_ids)
        ).execute()

        result = []
        for item in vids.get("items", []):
            s = item.get("statistics", {})
            pub = item["snippet"].get("publishedAt", "")[:10]
            result.append({
                "id": item["id"],
                "title": item["snippet"]["title"],
                "published_at": pub,
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "url": f"https://youtube.com/shorts/{item['id']}",
                "platform": "youtube",
            })
        return result  # playlist order = newest first

    except Exception as e:
        logger.warning(f"YT videos failed for {channel_name}: {e}")
        return []

def get_retention(channel_name: str, days: int = 28, max_videos: int = 25) -> list:
    """
    Per-video retention metrics for recent videos via YouTube Analytics v2:
    views, averageViewPercentage (the retention signal), averageViewDuration,
    likes, comments, shares. Requires yt-analytics.readonly scope
    (one-time: run setup_yt_analytics.py per channel).
    """
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    import datetime

    cred_name = channel_name.replace(" ", "_")
    creds = None
    for fname in [f"youtube_analytics_{cred_name}.json", f"youtube_credentials_{cred_name}.json"]:
        p = BASE_DIR / fname
        if p.exists():
            try:
                c = Credentials.from_authorized_user_file(str(p))
                if c.expired and c.refresh_token:
                    c.refresh(Request())
                    p.write_text(c.to_json())
                if c.valid:
                    creds = c
                    break
            except Exception:
                pass

    if not creds:
        return []

    try:
        analytics = build("youtubeAnalytics", "v2", credentials=creds)
        end = datetime.date.today()
        start = end - datetime.timedelta(days=days)
        res = analytics.reports().query(
            ids="channel==MINE",
            startDate=start.strftime("%Y-%m-%d"),
            endDate=end.strftime("%Y-%m-%d"),
            metrics="views,averageViewPercentage,averageViewDuration,likes,comments,shares",
            dimensions="video",
            sort="-views",
            maxResults=max_videos,
        ).execute()
        rows = res.get("rows", [])
        if not rows:
            return []

        # Join titles via the Data API (analytics rows only carry video ids)
        ids = [r[0] for r in rows]
        titles = {}
        yt = _build_yt(channel_name)
        if yt:
            for i in range(0, len(ids), 50):
                try:
                    resp = yt.videos().list(part="snippet", id=",".join(ids[i:i + 50])).execute()
                    for item in resp.get("items", []):
                        titles[item["id"]] = item["snippet"]["title"]
                except Exception:
                    pass

        result = []
        for r in rows:
            vid = str(r[0])
            result.append({
                "id": vid,
                "title": titles.get(vid, vid),
                "views": int(r[1]),
                "avg_view_pct": round(float(r[2]), 1),
                "avg_view_dur": round(float(r[3]), 1),
                "likes": int(r[4]),
                "comments": int(r[5]),
                "shares": int(r[6]),
                "url": f"https://youtube.com/shorts/{vid}",
            })
        return result
    except Exception as e:
        # Expected if scope yt-analytics.readonly is missing
        logger.debug(f"YT retention failed for {channel_name}: {e}")
        return []


def get_demographics(channel_name: str, metric: str = "views") -> list:
    """
    Fetch YouTube channel demographics via YouTube Analytics API.
    Returns Top 10 countries by views.
    Requires yt-analytics.readonly scope.
    """
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    import datetime

    cred_name = channel_name.replace(" ", "_")
    creds = None
    for fname in [f"youtube_analytics_{cred_name}.json", f"youtube_credentials_{cred_name}.json"]:
        p = BASE_DIR / fname
        if p.exists():
            try:
                c = Credentials.from_authorized_user_file(str(p))
                if c.expired and c.refresh_token:
                    c.refresh(Request())
                    p.write_text(c.to_json())
                if c.valid:
                    creds = c
                    break
            except Exception:
                pass
    
    if not creds:
        return []

    try:
        analytics = build("youtubeAnalytics", "v2", credentials=creds)
        today = datetime.date.today().strftime('%Y-%m-%d')
        res = analytics.reports().query(
            ids='channel==MINE',
            startDate='2000-01-01',
            endDate=today,
            metrics=metric,
            dimensions='country',
            sort=f'-{metric}',
            maxResults=10
        ).execute()
        
        countries = []
        for row in res.get("rows", []):
            if len(row) >= 2:
                countries.append({"country": row[0], "count": int(row[1])})
        return countries
    except Exception as e:
        # Expected if scope yt-analytics.readonly is missing
        logger.debug(f"YT demographics failed for {channel_name}: {e}")
        return []
