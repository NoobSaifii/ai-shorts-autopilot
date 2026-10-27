"""
Daily orchestration script — runs once, processes every configured channel in a
randomly-shuffled order (different every calendar day), uploads to YouTube
and Meta (FB + IG), and sends Gmail notifications at each step.

Usage:
    python daily_runner.py              # process all channels
    python daily_runner.py --channel "Blade Archives"  # single channel test
"""

import argparse
import asyncio
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import notifier
from scheduler import get_channel_config, run_generation_for_channel
from utils.disk import log_free, purge
from uploaders.meta import MetaUploader
from uploaders.youtube import YouTubeUploader
from uploaders.tiktok import TikTokUploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("daily_runner")

DEFAULT_PLATFORMS = ("youtube", "instagram", "facebook")


def channel_platforms(ch: dict) -> set:
    """Platforms this channel publishes to (config `platforms:` list)."""
    return {str(p).strip().lower() for p in (ch.get("platforms") or DEFAULT_PLATFORMS)}


# ── Helpers ────────────────────────────────────────────────────────────────────

LOW_DISK_GB = 5.0


def purge_channel_output(output_root: Path, names, label: str) -> float:
    """Delete the render folders of the given channels. Returns MB freed."""
    return sum(purge(output_root / n, f"{label}: {n}") for n in names)


def get_daily_order(channels: list) -> list:
    """
    Returns all enabled channels in a random order. Channels marked
    `priority: true` in config always run first. The order is reproducible
    within the same calendar day.
    """
    uploadable = [ch for ch in channels if ch.get("enabled", True)]
    random.seed(date.today().toordinal())
    random.shuffle(uploadable)
    uploadable.sort(key=lambda ch: not ch.get("priority", False))
    return uploadable


# ── Per-channel processing ─────────────────────────────────────────────────────

async def process_one_channel(ch: dict, no_upload: bool = False) -> dict:
    """
    Generate one video for this channel, then upload to YouTube and Meta.
    Returns a result dict with success/failure info.
    no_upload=True → generation + metadata only (local QA mode).
    """
    name       = ch["name"]
    upload_cfg = ch.get("upload", {})
    platforms  = channel_platforms(ch)
    result     = {
        "channel": name,
        "success": False,
        "topic":   "",
        "error":   "",
        "uploads": {"YouTube": False, "Facebook": False, "Instagram": False},
    }

    # ── 1. Generate video (retry transient network/SSL errors) ─────────────────
    # SQLite resume makes a retry cheap: already-finished scenes are reused, so a
    # transient glitch (e.g. "EOF occurred in violation of protocol") no longer
    # loses the whole channel.
    logger.info(f"[{name}] Generating video...")
    gen_attempts = 3
    video_path = None
    for attempt in range(1, gen_attempts + 1):
        try:
            video_path = await run_generation_for_channel(name)
            break
        except Exception as e:
            msg = str(e).lower()
            transient = any(k in msg for k in (
                "eof occurred", "ssl", "timed out", "timeout", "connection reset",
                "connection aborted", "broken pipe", "temporarily unavailable",
                "remoteprotocol", "readerror", "connecterror", "503", "502", "429",
            ))
            if attempt < gen_attempts and transient:
                wait = 5 * attempt
                logger.warning(
                    f"[{name}] generation hit a transient error (attempt {attempt}/{gen_attempts}) — "
                    f"retry in {wait}s (resume reuses finished scenes): {str(e)[:160]}"
                )
                await asyncio.sleep(wait)
                continue
            result["error"] = f"Generation failed: {e}"
            logger.error(f"[{name}] {result['error']}")
            return result

    # None = no pending topics in Excel (already uploaded today) — skip gracefully
    if video_path is None:
        result["success"] = True
        result["skipped"] = True
        result["topic"]   = "(no pending topics)"
        logger.info(f"[{name}] No pending topics — skipping (already uploaded today)")
        return result

    if not Path(video_path).exists():
        result["error"] = "Video file not found after generation"
        logger.error(f"[{name}] {result['error']}")
        return result

    # ── 2. Read metadata ───────────────────────────────────────────────────────
    # metadata.json is written inside the final/ subfolder alongside the video
    metadata_path = Path(video_path).parent / "metadata.json"
    if not metadata_path.exists():
        result["error"] = f"metadata.json missing at {metadata_path}"
        logger.error(f"[{name}] {result['error']}")
        return result

    with open(metadata_path, encoding="utf-8") as f:
        meta = json.load(f)

    result["topic"] = meta.get("viral_title") or meta.get("title", "")
    title       = meta.get("viral_title", "Video")
    desc        = meta.get("short_description", "")
    tags        = meta.get("hashtags", [])
    engage_q    = str(meta.get("engagement_question", "")).strip()
    desc_parts  = [p for p in (desc, engage_q, " ".join(tags)) if p]
    full_desc   = "\n\n".join(desc_parts)
    yt_token    = f"youtube_credentials_{name.replace(' ', '_')}.json"

    # FB + YT + IG all take the shorts cut — one variant instead of two.
    # Meta documents a 3–90s spec for the Reels API, but Facebook accepts and
    # distributes longer reels fine in practice (measured on the 659k-follower
    # page: a 122s API-published reel pulled ~1.9k plays). So this is tidiness,
    # not a workaround — don't read a hard limit into it.
    full_video   = meta.get("full_path",   video_path)
    shorts_video = meta.get("shorts_path", video_path)
    thumb_v      = meta.get("thumbnail_v", "")    # 9:16 portrait — used for YT + FB + IG (all vertical Shorts/Reels)
    thumb_yt     = meta.get("thumbnail_yt", "")   # 16:9 landscape — generated but unused (kept for future long-form)

    if no_upload:
        result["success"]   = True
        result["no_upload"] = True
        logger.info(f"[{name}] --no-upload: generation complete, skipping all uploads")
        logger.info(f"[{name}]   Full video  : {full_video}")
        logger.info(f"[{name}]   Shorts video: {shorts_video}")
        return result

    # ── 3. YouTube upload (≤2:55 shorts version) ──────────────────────────────
    if "youtube" in platforms:
        logger.info(f"[{name}] Uploading to YouTube (shorts)...")
        try:
            yt = YouTubeUploader(token_file=yt_token)
            if yt.upload_video(shorts_video, title, full_desc, tags, thumbnail_path=thumb_v):
                result["uploads"]["YouTube"] = True
                logger.info(f"[{name}] YouTube ✓")
            else:
                logger.warning(f"[{name}] YouTube upload failed after all retries")
        except Exception as e:
            logger.warning(f"[{name}] YouTube upload failed: {e}")

    # ── 4. Meta — FB + IG both on the shorts cut ──────────────────────────────
    _ig_public_url = ""  # R2/temp URL from IG upload; reused by TikTok below
    if upload_cfg and platforms & {"facebook", "instagram"}:
        try:
            m = MetaUploader(
                fb_page_id   = upload_cfg["fb_page_id"],
                ig_user_id   = upload_cfg["ig_user_id"],
                access_token = upload_cfg["meta_access_token"],
            )

            # Facebook → shorts cut (same file as IG/YT)
            if "facebook" in platforms:
                logger.info(f"[{name}] Facebook upload (shorts)...")
                if m.upload_to_facebook_reels(shorts_video, full_desc, thumbnail_path=thumb_v):
                    result["uploads"]["Facebook"] = True
                    logger.info(f"[{name}] Facebook ✓")
                else:
                    logger.warning(f"[{name}] Facebook upload failed after all retries")
            else:
                logger.info(f"[{name}] Facebook upload off for this channel — skipping")

            # Instagram → speed-adjusted ≤2:55
            if "instagram" in platforms:
                logger.info(f"[{name}] Instagram upload (shorts)...")
                if m.upload_to_instagram_reels(shorts_video, full_desc, cover_path=thumb_v):
                    result["uploads"]["Instagram"] = True
                    logger.info(f"[{name}] Instagram ✓")
                else:
                    logger.warning(f"[{name}] Instagram upload failed after all retries")

            # Note: TikTok PULL_FROM_URL requires domain ownership verification
            # (pub-*.r2.dev is Cloudflare's domain — cannot be verified).
            # TikTok uses FILE_UPLOAD instead; last_ig_public_url kept for future use
            # if a custom verified domain is configured on R2.
        except Exception as e:
            logger.warning(f"[{name}] Meta upload failed: {e}")

    # ── 5. TikTok upload (shorts version) ───────────────────────────────────────
    if "tiktok" in platforms:
        logger.info(f"[{name}] Uploading to TikTok...")
        try:
            import yaml
            with open("config.yaml") as f:
                cfg = yaml.safe_load(f)
            sheet_id = cfg.get("google_sheet_id", "")

            tiktok = TikTokUploader(channel_name=name, sheet_id=sheet_id, sa_file="google_service_account.json")
            _tk_success = False
            for _tk_attempt in range(1, 4):
                if tiktok.upload_video(shorts_video, title, tags):
                    result["uploads"]["TikTok"] = True
                    logger.info(f"[{name}] TikTok ✓")
                    _tk_success = True
                    break
                if _tk_attempt < 3:
                    _wait = _tk_attempt * 30
                    logger.warning(f"[{name}] TikTok attempt {_tk_attempt} failed — retry in {_wait}s")
                    await asyncio.sleep(_wait)
            if not _tk_success:
                logger.warning(f"[{name}] TikTok upload failed after 3 attempts")
        except Exception as e:
            logger.warning(f"[{name}] TikTok upload failed: {e}")

    required_uploads = []
    if "youtube" in platforms:
        required_uploads.append("YouTube")
    if upload_cfg:
        if "instagram" in platforms:
            required_uploads.append("Instagram")
        if "facebook" in platforms:
            required_uploads.append("Facebook")
    # TikTok is best-effort: its Content-Posting API processes async and the
    # uploader only polls ~100s, so a slow-but-successful publish can report
    # failure. Keeping it out of required_uploads avoids false channel errors
    # (the topic is already marked done live, so nothing re-uploads).
        
    failed_uploads = [platform for platform in required_uploads if not result["uploads"].get(platform)]
    if failed_uploads:
        result["error"] = "Upload failed: " + ", ".join(failed_uploads)
        logger.error(f"[{name}] {result['error']}")
        return result

    result["success"] = True
    return result


# ── Topics status commit ───────────────────────────────────────────────────────

def _commit_topics_status(channel_name: str, excel: str = "topics.xlsx"):
    """
    Commit + push the updated Excel topics file after each channel upload.

    CRITICAL: if this push never succeeds, the next daily run will re-process
    the same topic. So we retry the push up to 5 times (pull --rebase each
    attempt) and log a CRITICAL error if all attempts fail.
    """
    safe_name = channel_name.replace(" ", "_")
    msg = f"chore: mark {safe_name} done [skip ci]"

    if not os.path.exists(excel):
        logger.error(f"[{channel_name}] CRITICAL: '{excel}' missing — topics status NOT saved")
        return

    def _git(args, check=True):
        return subprocess.run(["git"] + args, check=check, capture_output=True, text=True)

    def _clean_git_state():
        # Clear any half-finished rebase/merge left by a prior interrupted attempt
        # (this is what caused the "already a rebase-merge directory" hang).
        _git(["rebase", "--abort"], check=False)
        _git(["merge", "--abort"], check=False)
        for p in (".git/rebase-merge", ".git/rebase-apply"):
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
            except OSError:
                pass

    # Bulletproof commit+push that works in GitHub Actions' detached-HEAD checkout
    # and never gets stuck on a binary-file rebase conflict:
    #   clean any stuck state → fetch → hard-reset to remote → re-apply OUR Excel
    #   → commit → push HEAD:main. No `pull --rebase`, so no conflict, no hang.
    max_attempts = 5
    ours = excel + ".ours"
    for attempt in range(1, max_attempts + 1):
        try:
            _clean_git_state()
            _git(["fetch", "origin", "main"])
            shutil.copy2(excel, ours)              # preserve our just-marked topics
            _git(["reset", "--hard", "FETCH_HEAD"])  # land exactly on latest remote
            shutil.move(ours, excel)               # restore our version on top
            _git(["add", excel])
            if _git(["diff", "--staged", "--quiet"], check=False).returncode == 0:
                logger.info(f"[{channel_name}] topics already up to date on GitHub ✓")
                return
            _git(["commit", "-m", msg])
            _git(["push", "origin", "HEAD:main"])
            logger.info(f"[{channel_name}] topics status pushed to GitHub ✓ (attempt {attempt})")
            return
        except subprocess.CalledProcessError as e:
            detail = ((e.stderr or "") + (e.stdout or "")).strip()[-300:]
            if attempt < max_attempts:
                wait = 2 ** (attempt - 1)
                logger.warning(
                    f"[{channel_name}] commit/push failed (attempt {attempt}/{max_attempts}) — "
                    f"retry in {wait}s: {detail}"
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"[{channel_name}] CRITICAL: push failed after {max_attempts} attempts.\n"
                    f"  Topic '{safe_name}' IS marked done locally but was NOT pushed.\n"
                    f"  Error: {detail}"
                )
        finally:
            if os.path.exists(ours):
                try:
                    os.remove(ours)
                except OSError:
                    pass


def _restore_topics_snapshot(topics_path: Path, snapshot: bytes | None):
    if snapshot is None:
        return
    topics_path.parent.mkdir(parents=True, exist_ok=True)
    topics_path.write_bytes(snapshot)
    logger.info("--no-upload: restored topics file snapshot")


# ── Main daily run ─────────────────────────────────────────────────────────────

def run_daily(single_channel: str = None, skip_channels: list = None,
              no_upload: bool = False, keep_output: bool = False):
    _, config = get_channel_config("")   # load full config
    all_channels = config.get("channels", [])
    today = date.today().strftime("%d %B %Y")
    skip_set = set(skip_channels or [])
    topics_path = Path(config.get("topics_file", "topics.xlsx"))
    topics_snapshot = topics_path.read_bytes() if no_upload and topics_path.exists() else None

    # Renders are disposable once uploaded, and leftovers are what filled the
    # runner's disk mid-merge. QA mode keeps them so the output stays inspectable.
    output_root = Path(config.get("pipeline", {}).get("output_root", "output"))
    all_names = [ch["name"] for ch in all_channels]
    cleanup = not (no_upload or keep_output)
    if cleanup:
        log_free("before run", output_root)
        purge_channel_output(output_root, all_names, "pre-run cleanup")
        log_free("after pre-run cleanup", output_root)
    else:
        logger.info("Output cleanup disabled (--no-upload / --keep-output)")

    if single_channel:
        # Single-channel mode (for testing)
        channels = [ch for ch in all_channels if ch["name"] == single_channel]
        if not channels:
            logger.error(f"Channel '{single_channel}' not found in config.yaml")
            return 1
        ordered = channels
        notifier.send(f"🧪 <b>Test Run — {single_channel}</b> ({today})")
    else:
        ordered = get_daily_order(all_channels)
        # Remove explicitly skipped channels (already uploaded today)
        if skip_set:
            skipped_names = ", ".join(skip_set)
            logger.info(f"Skipping already-done channels: {skipped_names}")
            ordered = [ch for ch in ordered if ch["name"] not in skip_set]
        order_txt = "\n".join(f"{i+1}. {ch['name']}" for i, ch in enumerate(ordered))
        notifier.send(
            f"🚀 <b>Daily Run Started — {today}</b>\n\n"
            f"📋 Today's Order ({len(ordered)} channels):\n{order_txt}"
            + (f"\n\n⏭️ Skipped (done): {', '.join(skip_set)}" if skip_set else "")
        )

    results = []

    for ch in ordered:
        name = ch["name"]
        notifier.send(f"⏳ <b>Starting:</b> {name}")

        if cleanup and log_free(f"before {name}", output_root) < LOW_DISK_GB:
            logger.warning(f"Low disk before {name} — purging leftover renders")
            purge_channel_output(output_root, all_names, "low-disk purge")
            log_free(f"after low-disk purge ({name})", output_root)

        try:
            result = asyncio.run(process_one_channel(ch, no_upload=no_upload))
        except Exception as e:
            result = {
                "channel": name,
                "success": False,
                "topic":   "",
                "error":   str(e),
                "uploads": {},
            }

        results.append(result)
        if no_upload:
            _restore_topics_snapshot(topics_path, topics_snapshot)

        if result.get("skipped"):
            # Already uploaded today — no Telegram noise, no commit needed
            logger.info(f"[{name}] Skipped (no pending topics)")
        elif result["success"]:
            up    = result.get("uploads", {})
            plats = " | ".join(p for p, v in up.items() if v) or "none"
            notifier.send(
                f"✅ <b>{name}</b> — Done\n"
                f"📹 <i>{result['topic']}</i>\n"
                f"📤 {plats}"
            )
            # Commit updated topics status immediately after this channel.
            # Skipped when: QA mode (--no-upload), OR Google Sheets is the topics
            # source (mark_done already wrote it live — no git, no rebase bug).
            if not no_upload and not config.get("google_sheet_id"):
                _commit_topics_status(name, str(topics_path))
        else:
            notifier.send(
                f"❌ <b>ERROR — {name}</b>\n"
                f"🚨 {result['error'][:300]}"
            )

        # Uploads are done (or the channel failed) — the render is dead weight.
        if cleanup:
            purge(output_root / name, f"{name} render")
            log_free(f"after {name}", output_root)

    # ── Final summary ──────────────────────────────────────────────────────────
    ok      = [r for r in results if r["success"] and not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]
    err     = [r for r in results if not r["success"]]

    if single_channel:
        logger.info(f"Single-channel run complete: {len(ok)} ok, {len(err)} failed.")
        return 1 if err else 0

    lines = [
        f"🎬 <b>Daily Upload Complete — {today}</b>\n",
        f"✅ {len(ok)} uploaded | ⏭️ {len(skipped)} skipped | ❌ {len(err)} failed\n",
        "<b>📝 Topics Uploaded Today:</b>",
    ]
    for r in ok:
        lines.append(f"• <b>{r['channel']}</b>\n  → {r['topic']}")

    if err:
        lines.append("\n<b>⚠️ Failed:</b>")
        for r in err:
            lines.append(f"• {r['channel']}: {r['error'][:80]}")

    notifier.send("\n".join(lines))
    logger.info(f"Daily run complete: {len(ok)} ok, {len(err)} failed.")

    return 1 if err else 0


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily video pipeline runner")
    parser.add_argument(
        "--channel",
        type=str,
        default=None,
        help="Run for a single channel only (for testing)",
    )
    parser.add_argument(
        "--skip",
        type=str,
        default="",
        help="Comma-separated channel names to skip (already uploaded today)",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Generate only — skip YouTube/Meta uploads and the git commit (local QA)",
    )
    parser.add_argument(
        "--keep-output",
        action="store_true",
        help="Keep rendered videos on disk instead of purging them after each channel",
    )
    args = parser.parse_args()
    skip = [s.strip() for s in args.skip.split(",") if s.strip()]
    sys.exit(run_daily(single_channel=args.channel, skip_channels=skip,
                       no_upload=args.no_upload, keep_output=args.keep_output))
