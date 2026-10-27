"""Facebook page analytics — followers, reel views, and video stats (shared client)."""
import logging
import httpx

logger = logging.getLogger("analytics.facebook")
GRAPH = "https://graph.facebook.com/v19.0"

_shared_client: httpx.AsyncClient | None = None


def _client(timeout: float = 15.0) -> httpx.AsyncClient:
    if _shared_client is not None and not _shared_client.is_closed:
        return _shared_client
    return httpx.AsyncClient(timeout=timeout)


async def _get(url, params, timeout=15.0):
    c = _client(timeout)
    owned = c is not _shared_client
    try:
        r = await c.get(url, params=params)
        return r
    finally:
        if owned:
            await c.aclose()


_page_token_cache = {}

async def _get_page_token(page_id: str, system_token: str) -> str:
    """Fetch the Page Access Token using the System User Token, with caching to avoid rate limits."""
    cache_key = f"{page_id}_{system_token[-10:]}"
    if cache_key in _page_token_cache:
        return _page_token_cache[cache_key]

    try:
        r = await _get(f"{GRAPH}/{page_id}", {"fields": "access_token", "access_token": system_token})
        d = r.json()
        if "access_token" in d:
            _page_token_cache[cache_key] = d["access_token"]
            return d["access_token"]
    except Exception as e:
        logger.warning(f"Failed to fetch page token for {page_id}: {e}")
        
    return system_token  # Fallback to provided token if fetching fails


async def get_page_stats(page_id: str, token: str) -> dict:
    if not page_id or not token:
        return {"followers": 0, "error": "no_credentials"}
    try:
        page_token = await _get_page_token(page_id, token)
        r = await _get(
            f"{GRAPH}/{page_id}",
            {"fields": "followers_count,fan_count,name", "access_token": page_token},
        )
        d = r.json()
        if "error" in d:
            return {"followers": 0, "error": d["error"]["message"]}
        return {
            "followers": d.get("followers_count", d.get("fan_count", 0)),
            "page_name": d.get("name", ""),
            "error": None,
        }
    except Exception as e:
        return {"followers": 0, "error": repr(e)}


async def get_reel_views_total(page_id: str, token: str) -> tuple[int, list]:
    """Paginate through ALL video_reels and return (total_views, top_reels_list).
    Facebook /{page_id}/video_reels returns views directly — no per-reel insight calls needed.
    """
    if not page_id or not token:
        return 0, []

    page_token = await _get_page_token(page_id, token)
    all_reels = []
    url = f"{GRAPH}/{page_id}/video_reels"
    params = {
        "fields": "id,title,description,views,created_time",
        "limit": 100,
        "access_token": page_token,
    }

    try:
        while url:
            r = await _get(url, params, timeout=20.0)
            d = r.json()
            if "error" in d:
                logger.warning("FB video_reels (%s): %s", page_id, d["error"]["message"])
                break
            for reel in d.get("data", []):
                raw = reel.get("title") or reel.get("description") or "FB Reel"
                all_reels.append({
                    "id": reel["id"],
                    "title": raw[:80],
                    "published_at": reel.get("created_time", "")[:10],
                    "views": int(reel.get("views") or 0),
                    "url": f"https://facebook.com/{reel['id']}",
                    "platform": "facebook",
                })
            next_url = d.get("paging", {}).get("next")
            url = next_url if next_url else None
            params = {}  # next URL already carries all params
    except Exception as e:
        logger.warning("FB reel pagination failed (%s): %r", page_id, e)

    total_views = sum(r["views"] for r in all_reels)
    return total_views, all_reels


async def get_recent_videos(page_id: str, token: str, count: int = 10) -> list:
    """Return last N uploaded videos (non-reel) with view counts — used for display."""
    if not page_id or not token:
        return []
    try:
        page_token = await _get_page_token(page_id, token)
        r = await _get(
            f"{GRAPH}/{page_id}/videos",
            {
                "fields": "id,title,description,created_time,length,views",
                "limit": count,
                "access_token": page_token,
            },
            timeout=20.0,
        )
        d = r.json()
        if "error" in d:
            logger.warning("FB videos (%s): %s", page_id, d["error"]["message"])
            return []

        videos = []
        for v in d.get("data", []):
            raw = v.get("title") or (v.get("description") or "FB Video")
            videos.append({
                "id": v["id"],
                "title": raw[:80],
                "published_at": v.get("created_time", "")[:10],
                "views": int(v.get("views") or 0),
                "url": f"https://facebook.com/{v['id']}",
                "platform": "facebook",
            })
        return videos

    except Exception as e:
        logger.warning("FB video fetch failed: %r", e)
        return []


async def get_demographics(page_id: str, token: str, metric: str = "followers") -> list:
    """
    Fetch Facebook Page Demographics.
    Note: For New Pages Experience, country demographics are restricted without Business Manager / Advanced access.
    Returns an empty list for now gracefully to prevent errors, but can be updated later.
    """
    return []
