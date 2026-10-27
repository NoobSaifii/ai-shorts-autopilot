"""Analytics dashboard — real YT / FB / IG stats per brand."""
import sys
import time
import asyncio
import yaml
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analytics.youtube_analytics import get_channel_stats as yt_ch_stats, get_recent_videos as yt_videos, get_demographics as yt_demo
from analytics.facebook_analytics import get_page_stats as fb_page_stats, get_reel_views_total as fb_reel_totals, get_demographics as fb_demo
from analytics.instagram_analytics import get_account_stats as ig_acct_stats, get_recent_media as ig_media, get_demographics as ig_demo
from analytics.tiktok_analytics import get_account_stats as tk_acct_stats, get_recent_videos as tk_videos
import analytics.instagram_analytics as _ig_mod
import analytics.facebook_analytics as _fb_mod
import analytics.tiktok_analytics as _tk_mod

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("dashboard")
# Suppress noisy third-party loggers; show everything from analytics
for _noisy in ("uvicorn", "uvicorn.access", "httpx", "httpcore", "fastapi"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# Shared HTTP client — single connection pool for all FB/IG API calls
_http: httpx.AsyncClient = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http
    _http = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        timeout=httpx.Timeout(25.0, connect=10.0),
    )
    # Share client with analytics modules so they all reuse the same connection pool
    _ig_mod._shared_client = _http
    _fb_mod._shared_client = _http
    _tk_mod._shared_client = _http
    yield
    await _http.aclose()

app = FastAPI(title="AI Video Brand Dashboard", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "dashboard" / "templates"))

_cache: dict = {}
CACHE_TTL = 30 * 60  # 30 minutes

# Rate-limit: max 4 brands loading simultaneously (avoids connection floods)
_brand_sem = asyncio.Semaphore(4)


def load_config() -> dict:
    p = BASE_DIR / "config.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def _cached_sync(key: str, fn, *args):
    now = time.time()
    entry = _cache.get(key)
    if entry and now - entry["ts"] < CACHE_TTL:
        return entry["data"]
    data = fn(*args)
    _cache[key] = {"data": data, "ts": now}
    return data


async def _cached_async(key: str, coro_fn, *args):
    now = time.time()
    entry = _cache.get(key)
    if entry and now - entry["ts"] < CACHE_TTL:
        return entry["data"]
    data = await coro_fn(*args)
    _cache[key] = {"data": data, "ts": now}
    return data


def _top5(videos: list) -> list:
    return sorted(videos, key=lambda v: v.get("views", 0), reverse=True)[:5]


def _overall_top5(yt: list, fb: list, ig: list) -> list:
    return sorted(yt + fb + ig, key=lambda v: v.get("views", 0), reverse=True)[:5]


def _fmt(n) -> str:
    try:
        n = int(n or 0)
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)
    except Exception:
        return "0"


async def build_brand_data(ch_cfg: dict, sheet_id: str) -> dict:
    async with _brand_sem:  # max 4 brands in parallel to avoid connection floods
        name   = ch_cfg["name"]
        upload = ch_cfg.get("upload", {})
        pg_id  = upload.get("fb_page_id", "")
        ig_id  = upload.get("ig_user_id", "")
        token  = upload.get("meta_access_token", "")

        loop = asyncio.get_event_loop()
        yt_ch_fut    = loop.run_in_executor(None, lambda: _cached_sync(f"yt_ch_{name}", yt_ch_stats, name))
        yt_vids_fut  = loop.run_in_executor(None, lambda: _cached_sync(f"yt_v_{name}",  yt_videos,   name, 10))
        yt_demo_fut  = loop.run_in_executor(None, lambda: _cached_sync(f"yt_demo_{name}", yt_demo, name, "views"))

        fb_ch_task   = _cached_async(f"fb_ch_{name}",    fb_page_stats,   pg_id, token)
        fb_reels_task = _cached_async(f"fb_reels_{name}", fb_reel_totals, pg_id, token)
        ig_ch_task   = _cached_async(f"ig_ch_{name}",    ig_acct_stats,   ig_id, token)
        ig_vids_task = _cached_async(f"ig_v_{name}",     ig_media,        ig_id, token, 25)
        ig_demo_f_task = _cached_async(f"ig_demo_f_{name}", ig_demo, ig_id, token, "follower_demographics", None)
        ig_demo_r_task = _cached_async(f"ig_demo_r_{name}", ig_demo, ig_id, token, "reached_audience_demographics", "this_month")
        
        tk_ch_task   = _cached_async(f"tk_ch_{name}",    tk_acct_stats,   name, sheet_id)
        tk_vids_task = _cached_async(f"tk_v_{name}",     tk_videos,       name, sheet_id, 15)

        yt_ch, yt_vids, yt_demo_r, fb_ch, fb_reels_result, ig_ch, ig_vids, ig_demo_f_data, ig_demo_r_data, tk_ch, tk_vids = await asyncio.gather(
            asyncio.wrap_future(yt_ch_fut),
            asyncio.wrap_future(yt_vids_fut),
            asyncio.wrap_future(yt_demo_fut),
            fb_ch_task,
            fb_reels_task,
            ig_ch_task,
            ig_vids_task,
            ig_demo_f_task,
            ig_demo_r_task,
            tk_ch_task,
            tk_vids_task,
        )
        fb_video_views, fb_all_reels = fb_reels_result

    yt_views       = yt_ch.get("views", 0)
    ig_total_views = sum(v.get("views", 0) for v in ig_vids)
    tk_total_views = sum(v.get("views", 0) for v in tk_vids)
    total_followers = (yt_ch.get("subscribers", 0)
                       + fb_ch.get("followers", 0)
                       + ig_ch.get("followers", 0)
                       + tk_ch.get("followers", 0))
    total_views = yt_views + fb_video_views + ig_total_views + tk_total_views

    fb_recent = fb_all_reels[:10]
    ig_recent = ig_vids[:10]
    tk_recent = tk_vids[:10]

    return {
        "name": name,
        "youtube": {
            **yt_ch,
            "recent_videos": yt_vids,
            "top5": _top5(yt_vids),
            "views_fmt": _fmt(yt_views),
            "subs_fmt":  _fmt(yt_ch.get("subscribers", 0)),
            "demographics_reach": yt_demo_r,
        },
        "facebook": {
            **fb_ch,
            "recent_videos": fb_recent,
            "top5": _top5(fb_all_reels),
            "followers_fmt":   _fmt(fb_ch.get("followers", 0)),
            "video_views":     fb_video_views,
            "video_views_fmt": _fmt(fb_video_views),
            "video_count":     len(fb_all_reels),
        },
        "instagram": {
            **ig_ch,
            "recent_media": ig_recent,
            "top5": _top5(ig_vids),
            "followers_fmt":   _fmt(ig_ch.get("followers", 0)),
            "total_views":     ig_total_views,
            "total_views_fmt": _fmt(ig_total_views),
            "reel_count":      len(ig_vids),
            "demographics_followers": ig_demo_f_data,
            "demographics_reach":     ig_demo_r_data,
        },
        "tiktok": {
            **tk_ch,
            "recent_videos": tk_recent,
            "top5": _top5(tk_vids),
            "followers_fmt": _fmt(tk_ch.get("followers", 0)),
            "total_views": tk_total_views,
            "total_views_fmt": _fmt(tk_total_views),
            "video_count": tk_ch.get("videos", len(tk_vids)),
        },
        "overall_top5":        _overall_top5(yt_vids, fb_all_reels, ig_vids + tk_vids),
        "total_views":         total_views,
        "total_views_fmt":     _fmt(total_views),
        "total_followers":     total_followers,
        "total_followers_fmt": _fmt(total_followers),
        "yt_views_fmt":        _fmt(yt_views),
        "fb_views_fmt":        _fmt(fb_video_views),
        "ig_views_fmt":        _fmt(ig_total_views),
        "tk_views_fmt":        _fmt(tk_total_views),
    }


@app.get("/")
async def dashboard(request: Request):
    config   = load_config()
    channels = config.get("channels", [])
    sheet_id = config.get("google_sheet_id", "")

    brands = await asyncio.gather(*[build_brand_data(ch, sheet_id) for ch in channels])
    brands = sorted(brands, key=lambda b: b["total_followers"], reverse=True)

    cache_age = 0
    if _cache:
        oldest = min(v["ts"] for v in _cache.values())
        cache_age = int((time.time() - oldest) / 60)

    return templates.TemplateResponse("index.html", {
        "request":        request,
        "brands":         brands,
        "cache_age_mins": cache_age,
        "cache_ttl_mins": CACHE_TTL // 60,
    })


@app.get("/refresh")
async def refresh():
    _cache.clear()
    return RedirectResponse(url="/")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081, reload=False)
