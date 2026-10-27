"""Retention feedback loop: daily per-video snapshots + weekly Telegram digest.

Snapshots land in analytics/history/<Safe_Name>.json (committed by CI), so over
time you can see exactly which hooks/topics hold viewers — and tune the prompts.
Everything here is best-effort: missing tokens/data never break the daily run.
"""

import json
import logging
from datetime import date
from pathlib import Path

import notifier
from analytics.youtube_analytics import get_retention

logger = logging.getLogger("analytics.retention")

HISTORY_DIR = Path(__file__).resolve().parent / "history"
KEEP_SNAPSHOTS = 90          # ~3 months of daily snapshots per channel
MIN_VIEWS_FOR_DIGEST = 50    # ignore videos with too few views to judge


def _channel_name(ch) -> str:
    return ch["name"] if isinstance(ch, dict) else str(ch)


def collect_and_store(channels) -> int:
    """Append today's retention snapshot for every channel with analytics creds."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    collected = 0

    for ch in channels:
        name = _channel_name(ch)
        try:
            videos = get_retention(name)
        except Exception as e:
            logger.warning(f"[{name}] retention fetch failed: {e}")
            continue
        if not videos:
            continue

        f = HISTORY_DIR / f"{name.replace(' ', '_')}.json"
        history = []
        if f.exists():
            try:
                history = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history = [h for h in history if h.get("date") != today]
        history.append({"date": today, "videos": videos})
        history = history[-KEEP_SNAPSHOTS:]
        f.write_text(json.dumps(history, indent=1, ensure_ascii=False), encoding="utf-8")
        collected += 1

    logger.info(f"retention snapshots stored for {collected}/{len(list(channels))} channels")
    return collected


def send_weekly_digest(channels) -> None:
    """Telegram digest: best/worst averageViewPercentage per channel —
    i.e. which hooks kept viewers and which lost them."""
    lines = ["📊 <b>Weekly Retention Digest</b>", ""]
    found = False

    for ch in channels:
        name = _channel_name(ch)
        f = HISTORY_DIR / f"{name.replace(' ', '_')}.json"
        if not f.exists():
            continue
        try:
            history = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not history:
            continue

        videos = history[-1].get("videos", [])
        rated = [
            v for v in videos
            if v.get("views", 0) >= MIN_VIEWS_FOR_DIGEST and v.get("avg_view_pct") is not None
        ]
        if not rated:
            continue
        rated.sort(key=lambda v: v["avg_view_pct"], reverse=True)
        best, worst = rated[0], rated[-1]

        found = True
        lines.append(f"<b>{name}</b>")
        lines.append(f"  ✅ {best['avg_view_pct']}% watched — {best['title'][:55]}")
        if worst is not best:
            lines.append(f"  ⚠️ {worst['avg_view_pct']}% watched — {worst['title'][:55]}")
        lines.append("")

    if found:
        lines.append("<i>High % = that hook/topic style works. Feed it back into the prompts.</i>")
        notifier.send("\n".join(lines))
        logger.info("weekly retention digest sent")
    else:
        logger.info("weekly digest: no retention data yet (run setup_yt_analytics.py?)")
