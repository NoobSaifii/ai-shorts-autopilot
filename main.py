"""
AI Video Generator — Python Pipeline
=====================================
Replacement for n8n workflow. Processes topics from topics.xlsx (or Google Sheets)
and generates fully produced YouTube Shorts videos.

Usage:
  python main.py                          # Interactive — asks channel each time
  python main.py --channel "Restricted Lore"   # Lock to one channel
  python main.py --dry-run                # Preview pending topics (no API calls)
  python main.py --list-jobs              # Show past job history
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Force UTF-8 encoding for Windows console to support emojis and special characters
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from modules.topics import TopicsManager
from modules.tts import ensure_kokoro_running
from pipeline.orchestrator import run_topic
from utils.database import Database
from utils.logger import setup_logger, make_progress

console = Console()


def load_config(path: str = "config.yaml") -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        console.print(f"[red]config.yaml not found at {cfg_path.resolve()}[/red]")
        sys.exit(1)
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def ask_channel(config: dict, locked_channel: str = "") -> dict:
    """Show channel selection menu and return chosen channel dict."""
    channels = config.get("channels", [])
    if not channels:
        console.print("[red]No channels defined in config.yaml[/red]")
        sys.exit(1)

    if locked_channel:
        matched = [c for c in channels if c["name"].lower() == locked_channel.lower()]
        if not matched:
            console.print(f"[red]Channel '{locked_channel}' not found in config.yaml[/red]")
            sys.exit(1)
        return matched[0]

    console.print()
    console.print(Panel.fit(
        Text("AI Video Generator", style="bold cyan", justify="center"),
        border_style="cyan",
    ))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Num", style="bold yellow", width=4)
    table.add_column("Channel", style="white")

    for i, ch in enumerate(channels, 1):
        table.add_row(f"[{i}]", ch["name"])

    console.print(table)
    console.print()

    valid = [str(i) for i in range(1, len(channels) + 1)]
    choice = Prompt.ask(
        "[bold]Kaunse channel ke liye video banana hai?[/bold]",
        choices=valid,
        show_choices=True,
    )

    return channels[int(choice) - 1]


def cmd_list_jobs(db: Database):
    jobs = db.list_jobs()
    if not jobs:
        console.print("[yellow]Koi job nahi mili abhi tak.[/yellow]")
        return

    table = Table(title="Pipeline Jobs", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Topic", max_width=50)
    table.add_column("Title", max_width=28)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Started", width=16)

    colors = {"running": "yellow", "completed": "green", "failed": "red"}
    for i, job in enumerate(jobs, 1):
        s = job.get("status", "")
        table.add_row(
            str(i),
            job["topic"][:50],
            (job.get("title") or "")[:28],
            f"[{colors.get(s, 'white')}]{s}[/{colors.get(s, 'white')}]",
            (job.get("created_at") or "")[:16],
        )
    console.print(table)


def cmd_dry_run(topics_manager: TopicsManager, config: dict):
    channels = config.get("channels", [])
    for ch in channels:
        pending = topics_manager.get_pending_topics(sheet_name=ch["sheet"])
        console.print(f"\n[bold cyan]{ch['name']}[/bold cyan] ({ch['sheet']}) — [yellow]{len(pending)} pending[/yellow]")
        if pending:
            t = Table(show_header=True, show_lines=False, box=None, padding=(0, 1))
            t.add_column("#", style="dim", width=5)
            t.add_column("Topic", max_width=65)
            t.add_column("Series", max_width=25)
            for row in pending[:5]:
                t.add_row(str(row.number), row.topic[:65], row.series_name)
            console.print(t)
            if len(pending) > 5:
                console.print(f"  [dim]... aur {len(pending)-5} topics[/dim]")
    console.print("\n[yellow]Dry run — koi API call nahi hui.[/yellow]")


async def process_one_video(
    channel: dict,
    config: dict,
    db: Database,
    topics_manager: TopicsManager,
    progress,
) -> bool:
    """Process next pending topic for the given channel. Returns True if video was made."""
    sheet = channel["sheet"]
    topic_row = topics_manager.get_next_pending(sheet_name=sheet)

    if not topic_row:
        console.print(f"\n[yellow]{channel['name']} mein koi pending topic nahi.[/yellow]")
        return False

    console.print(f"\n[bold]Channel:[/bold] {channel['name']}")
    console.print(f"[bold]Topic:[/bold] {topic_row.topic[:80]}")
    console.print(f"[bold]Series:[/bold] {topic_row.series_name} | Episode {topic_row.episode_no}\n")

    # Override config with channel specific settings
    if "voice" in channel:
        config.setdefault("kokoro", {})["voice"] = channel["voice"]
    if "speed" in channel:
        config.setdefault("kokoro", {})["speed"] = float(channel["speed"])
    if "voice_gain" in channel:
        config.setdefault("kokoro", {})["voice_gain"] = float(channel["voice_gain"])
    if "music_path" in channel:
        config.setdefault("pipeline", {})["music_path"] = channel["music_path"]
    if "music_mood" in channel:
        config.setdefault("pipeline", {})["music_mood"] = channel["music_mood"]
    if "subtitle_color" in channel:
        config.setdefault("video", {})["subtitle_color"] = channel["subtitle_color"]

    try:
        final = await run_topic(
            topic_row=topic_row,
            config=config,
            db=db,
            topics_manager=topics_manager,
            sheet_name=sheet,
            channel_name=channel["name"],
            progress=progress,
        )
        if final:
            console.print(f"\n[bold green][SUCCESS] Video ready:[/bold green] {final}")
            
            # --- START API UPLOAD PROCESS ---
            import json
            from uploaders.youtube import YouTubeUploader
            from uploaders.meta import MetaUploader
            
            metadata_path = Path(final).parent / "metadata.json"
            title, description, tags = "", "", []
            thumb_yt, thumb_v = "", ""
            if metadata_path.exists():
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    title = meta.get("viral_title", meta.get("title", ""))
                    description = meta.get("short_description", "")
                    tags = meta.get("hashtags", [])
                    thumb_yt = meta.get("thumbnail_yt", "")
                    thumb_v = meta.get("thumbnail_v", "")
            
            upload_cfg = channel.get("upload", {})
            if upload_cfg:
                console.print("\n[bold cyan]Starting API Uploads...[/bold cyan]")
                
                # YouTube Upload
                try:
                    # Use channel-specific token file to support multiple YouTube channels
                    token_filename = f"youtube_credentials_{channel['name'].replace(' ', '_')}.json"
                    yt = YouTubeUploader(token_file=token_filename)
                    yt.upload_video(final, title, description, tags, thumbnail_path=thumb_v)
                except Exception as e:
                    console.print(f"[red]YouTube Upload Error:[/red] {e}")

                # Meta Upload (FB/IG)
                fb_page_id = upload_cfg.get("fb_page_id")
                ig_user_id = upload_cfg.get("ig_user_id")
                access_token = upload_cfg.get("meta_access_token")
                
                if fb_page_id and ig_user_id and access_token:
                    meta_up = MetaUploader(fb_page_id, ig_user_id, access_token)
                    caption = f"{title}\n\n{description}\n\n{' '.join(tags)}"
                    try:
                        meta_up.upload_to_facebook_reels(final, caption, thumbnail_path=thumb_v)
                    except Exception as e:
                        console.print(f"[red]FB Upload Error:[/red] {e}")

                    try:
                        meta_up.upload_to_instagram_reels(final, caption, cover_path=thumb_v)
                    except Exception as e:
                        console.print(f"[red]IG Upload Error:[/red] {e}")
            
        return True
    except Exception as e:
        console.print(f"\n[bold red][ERROR] Failed:[/bold red] {e}")
        return False


async def run_pipeline(
    config: dict,
    db: Database,
    topics_manager: TopicsManager,
    locked_channel: str,
):
    # Auto-start Kokoro
    kokoro_cfg = config.get("kokoro", {})
    console.print("[cyan]Kokoro TTS check kar raha hoon...[/cyan]")
    await ensure_kokoro_running(
        base_url=kokoro_cfg.get("base_url", "http://localhost:8002"),
        script_path=kokoro_cfg.get("script_path", ""),
        timeout=90,
    )

    with make_progress() as progress:
        while True:
            channel = ask_channel(config, locked_channel)
            remaining = topics_manager.pending_count(sheet_name=channel["sheet"])
            console.print(f"[dim]{channel['name']} mein {remaining} pending topics hain.[/dim]")

            await process_one_video(channel, config, db, topics_manager, progress)

            console.print()
            again = Prompt.ask(
                "[bold]Agla video banana hai?[/bold]",
                choices=["y", "n"],
                default="y",
            )
            if again == "n":
                console.print("\n[cyan]Pipeline band kar raha hoon. Allah Hafiz![/cyan]")
                break


def main():
    parser = argparse.ArgumentParser(
        description="AI Video Generator — Python Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--channel", type=str, default="", help="Channel name (locks to this channel)")
    parser.add_argument("--dry-run", action="store_true", help="Show pending topics, no API calls")
    parser.add_argument("--list-jobs", action="store_true", help="List all pipeline jobs")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logger(config.get("logs_dir", "logs"))

    db = Database(config.get("db_path", "pipeline_jobs.db"))
    topics_manager = TopicsManager(
        config["topics_file"],
        sheet_id=config.get("google_sheet_id", ""),
        sa_file=config.get("google_sa_file", ""),
    )

    if args.list_jobs:
        cmd_list_jobs(db)
        return

    if args.dry_run:
        cmd_dry_run(topics_manager, config)
        return

    asyncio.run(run_pipeline(config, db, topics_manager, args.channel))


if __name__ == "__main__":
    main()
