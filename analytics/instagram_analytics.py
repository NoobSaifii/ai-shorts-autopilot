"""Instagram analytics — account stats and reel views (parallel insights, shared client)."""
import asyncio
import logging
import httpx

logger = logging.getLogger("analytics.instagram")
GRAPH = "https://graph.facebook.com/v19.0"

# Shared client used when called from the dashboard (set by app.py at startup)
_shared_client: httpx.AsyncClient | None = None


def _client(timeout: float = 15.0) -> httpx.AsyncClient:
    """Return shared client if available, otherwise create a temporary one."""
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


async def get_account_stats(ig_user_id: str, token: str) -> dict:
    if not ig_user_id or not token:
        return {"followers": 0, "error": "no_credentials"}
    try:
        r = await _get(
            f"{GRAPH}/{ig_user_id}",
            {"fields": "followers_count,media_count,username", "access_token": token},
        )
        d = r.json()
        if "error" in d:
            return {"followers": 0, "error": d["error"]["message"]}
        return {
            "followers": d.get("followers_count", 0),
            "media_count": d.get("media_count", 0),
            "username": d.get("username", ""),
            "error": None,
        }
    except Exception as e:
        return {"followers": 0, "error": repr(e)}


async def get_recent_media(ig_user_id: str, token: str, count: int = 10) -> list:
    """Return last N reels with real view counts (plays metric)."""
    if not ig_user_id or not token:
        return []

    # Get media list
    try:
        r = await _get(
            f"{GRAPH}/{ig_user_id}/media",
            {
                "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink",
                "limit": count,
                "access_token": token,
            },
            timeout=20.0,
        )
        d = r.json()
        if "error" in d:
            logger.warning(f"IG media list ({ig_user_id}): {d['error']['message']}")
            return []
    except Exception as e:
        logger.warning(f"IG media list failed ({ig_user_id}): {repr(e)}")
        return []

    video_items = [
        item for item in d.get("data", [])
        if item.get("media_type") in ("VIDEO", "REEL")
    ]
    if not video_items:
        return []

    # Fetch plays for all reels in a SINGLE batch API call (max 50 per batch)
    import json
    batch = []
    for item in video_items:
        batch.append({
            "method": "GET",
            "relative_url": f"v19.0/{item['id']}/insights?metric=views&period=lifetime"
        })

    plays_results = []
    try:
        c = _client(25.0)
        owned = c is not _shared_client
        try:
            r = await c.post(
                "https://graph.facebook.com/v19.0",
                data={"access_token": token, "batch": json.dumps(batch)}
            )
            batch_data = r.json()
            for bd in batch_data:
                val = 0
                if bd.get("code") == 200:
                    body = json.loads(bd.get("body", "{}"))
                    for entry in body.get("data", []):
                        vals = entry.get("values", [])
                        if vals:
                            val = int(vals[-1].get("value", 0))
                else:
                    logger.warning("IG batch insight error: %s", bd.get("body"))
                plays_results.append(val)
        finally:
            if owned:
                await c.aclose()
    except Exception as exc:
        logger.warning("IG batch request failed: %r", exc)
        plays_results = [0] * len(video_items)

    items = []
    for item, plays in zip(video_items, plays_results):
        caption = (item.get("caption") or "").strip()
        items.append({
            "id": item["id"],
            "title": caption[:80] if caption else "Instagram Reel",
            "published_at": item.get("timestamp", "")[:10],
            "views": plays,
            "likes": item.get("like_count", 0),
            "comments": item.get("comments_count", 0),
            "url": item.get("permalink", ""),
            "platform": "instagram",
        })
    return items

async def get_demographics(ig_user_id: str, token: str, metric: str = "follower_demographics", timeframe: str = None) -> list:
    """Fetch Top 10 Countries for a specific demographic metric from IG Insights."""
    if not ig_user_id or not token:
        return []
    try:
        params = {
            "metric": metric,
            "metric_type": "total_value",
            "breakdown": "country",
            "access_token": token
        }
        if timeframe:
            params["timeframe"] = timeframe
        else:
            params["period"] = "lifetime"

        r = await _get(f"{GRAPH}/{ig_user_id}/insights", params, timeout=15.0)
        data = r.json()
        countries = []
        for d in data.get("data", []):
            tv = d.get("total_value", {})
            breakdowns = tv.get("breakdowns", [])
            for b in breakdowns:
                for res in b.get("results", []):
                    dims = res.get("dimension_values", [])
                    dim = dims[0] if dims else "Unknown"
                    val = res.get("value", 0)
                    countries.append({"country": dim, "count": val})
        return sorted(countries, key=lambda x: x["count"], reverse=True)[:10]
    except Exception as e:
        logger.warning(f"IG demographics failed ({metric} - {ig_user_id}): {repr(e)}")
        return []
