import asyncio
import logging
import httpx
from utils.tiktok_auth import get_valid_tiktok_access_token

logger = logging.getLogger("analytics.tiktok")

# Use a shared client if provided by the dashboard lifecycle, otherwise fallback
_shared_client: httpx.AsyncClient = None

async def _get_client() -> httpx.AsyncClient:
    return _shared_client or httpx.AsyncClient()

async def _get_token_async(channel_name: str, sheet_id: str):
    """Read/refresh the TikTok token off the event loop.

    get_valid_tiktok_access_token does blocking I/O (Google Sheets + requests).
    Running it inline inside these coroutines starves the shared async client
    during the dashboard's parallel multi-channel load, which intermittently
    fails an unrelated channel. Push it to a thread instead.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_valid_tiktok_access_token, channel_name, sheet_id)

async def get_account_stats(channel_name: str, sheet_id: str) -> dict:
    """Fetch TikTok account stats like follower_count and likes_count."""
    token = await _get_token_async(channel_name, sheet_id)
    if not token:
        return {}
        
    url = "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,follower_count,following_count,likes_count,video_count"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        client = await _get_client()
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        
        user_data = data.get("data", {}).get("user", {})
        return {
            "followers": user_data.get("follower_count", 0),
            "likes": user_data.get("likes_count", 0),
            "videos": user_data.get("video_count", 0),
            "display_name": user_data.get("display_name", "")
        }
    except Exception as e:
        logger.error(f"Failed to fetch TikTok account stats for {channel_name}: {e!r}")
        return {}

async def get_recent_videos(channel_name: str, sheet_id: str, max_count: int = 10) -> list:
    """Fetch recent TikTok videos and their view counts."""
    token = await _get_token_async(channel_name, sheet_id)
    if not token:
        return []
        
    url = "https://open.tiktokapis.com/v2/video/list/?fields=id,title,view_count,like_count,comment_count,share_count,cover_image_url"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "max_count": max_count
    }
    
    try:
        client = await _get_client()
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        
        videos = data.get("data", {}).get("videos", [])
        formatted_videos = []
        for v in videos:
            formatted_videos.append({
                "id": v.get("id"),
                "title": v.get("title", "TikTok Video"),
                "views": v.get("view_count", 0),
                "likes": v.get("like_count", 0),
                "comments": v.get("comment_count", 0),
                "thumbnail": v.get("cover_image_url", ""),
                "platform": "tiktok"
            })
        return formatted_videos
    except Exception as e:
        logger.error(f"Failed to fetch TikTok video list for {channel_name}: {e!r}")
        return []
