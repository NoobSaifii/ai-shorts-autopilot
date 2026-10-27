"""Download CC0/public-domain background music from archive.org into the
per-mood folders under assets/music/. Safe for a public repo: only items whose
licenseurl is creativecommons publicdomain (CC0 / PD-mark) are accepted, and a
CREDITS.txt with source + license is written next to the files.

Usage:  python scripts/fetch_music.py [--per-mood 4]
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "assets" / "music"

UA = {"User-Agent": "Mozilla/5.0 (ai-video-pipeline; CC0 music fetcher)"}

# mood → archive.org search queries (tried in order until enough tracks).
# Scoped to collection:(netlabels) — curated artist-self-published releases,
# which avoids the mislabeled-copyright junk in the general audio collection.
MOOD_QUERIES = {
    "dark_mystery": [
        'collection:(netlabels) AND "dark ambient" drone',
        'collection:(netlabels) AND dark ambient atmosphere',
        'collection:(netlabels) AND mystery ambient',
    ],
    "eerie_horror": [
        'collection:(netlabels) AND horror ambient',
        'collection:(netlabels) AND creepy dark drone',
        'collection:(netlabels) AND ritual ambient',
    ],
    "epic_history": [
        'collection:(musopen) AND symphony',
        'collection:(musopen) AND requiem',
        'collection:(netlabels) AND epic orchestral',
        'collection:(netlabels) AND cinematic drums',
        'collection:(netlabels) AND medieval battle',
    ],
    "tense_science": [
        'collection:(netlabels) AND tension electronic ambient',
        'collection:(netlabels) AND "idm" dark minimal',
        'collection:(netlabels) AND glitch ambient experimental',
        'collection:(netlabels) AND minimal techno dark',
    ],
}

MIN_DUR, MAX_DUR = 50.0, 420.0   # seconds
MIN_BYTES = 700_000


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def search(query: str, rows: int = 15) -> list:
    q = (
        f"({query}) AND mediatype:(audio) AND "
        f"licenseurl:(*publicdomain*)"
    )
    url = (
        "https://archive.org/advancedsearch.php?"
        + urllib.parse.urlencode(
            {
                "q": q,
                "fl[]": "identifier",
                "sort[]": "downloads desc",
                "rows": str(rows),
                "page": "1",
                "output": "json",
            },
            doseq=True,
        )
    )
    try:
        data = http_json(url)
        return [d["identifier"] for d in data.get("response", {}).get("docs", [])]
    except Exception as e:
        print(f"  search failed ({query}): {e}")
        return []


def item_files(identifier: str) -> tuple:
    """Return (licenseurl, [(filename, size, length_s)]) of mp3/ogg files."""
    try:
        meta = http_json(f"https://archive.org/metadata/{identifier}")
    except Exception:
        return "", []
    lic = str(meta.get("metadata", {}).get("licenseurl", ""))
    out = []
    for f in meta.get("files", []):
        name = f.get("name", "")
        if not re.search(r"\.(mp3|ogg)$", name, re.I):
            continue
        try:
            size = int(f.get("size", 0))
        except (TypeError, ValueError):
            size = 0
        try:
            length = float(f.get("length", 0) or 0)
        except (TypeError, ValueError):
            # "mm:ss" form
            m = re.match(r"^(\d+):(\d+)", str(f.get("length", "")))
            length = int(m.group(1)) * 60 + int(m.group(2)) if m else 0
        out.append((name, size, length))
    return lic, out


def ffprobe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0.0


def safe_name(identifier: str, filename: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{identifier}_{Path(filename).stem}")
    return base[:80] + Path(filename).suffix.lower()


def fetch_mood(mood: str, queries: list, per_mood: int) -> list:
    folder = MUSIC_DIR / mood
    folder.mkdir(parents=True, exist_ok=True)
    have = [p for p in folder.iterdir() if p.suffix.lower() in (".mp3", ".ogg")]
    if len(have) >= per_mood:
        print(f"[{mood}] already has {len(have)} tracks — skipping")
        return []

    credits = []
    got = len(have)
    seen_items = set()

    for query in queries:
        if got >= per_mood:
            break
        print(f"[{mood}] searching: {query}")
        for ident in search(query):
            if got >= per_mood:
                break
            if ident in seen_items:
                continue
            seen_items.add(ident)

            lic, files = item_files(ident)
            if "publicdomain" not in lic:
                continue
            # best candidate file in this item: right duration, decent size
            files = [
                (n, s, l) for (n, s, l) in files
                if s >= MIN_BYTES and (l == 0 or MIN_DUR <= l <= MAX_DUR)
            ]
            if not files:
                continue
            files.sort(key=lambda x: -x[1])
            name, size, _ = files[0]

            dest = folder / safe_name(ident, name)
            if dest.exists():
                continue
            url = f"https://archive.org/download/{ident}/{urllib.parse.quote(name)}"
            print(f"  downloading: {ident} / {name} ({size//1024}KB)")
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as w:
                    w.write(r.read())
            except Exception as e:
                print(f"    failed: {e}")
                dest.unlink(missing_ok=True)
                continue

            dur = ffprobe_duration(dest)
            if dest.stat().st_size < MIN_BYTES or not (MIN_DUR <= dur <= MAX_DUR):
                print(f"    rejected (size={dest.stat().st_size}, dur={dur:.0f}s)")
                dest.unlink(missing_ok=True)
                continue

            got += 1
            credits.append(
                f"{dest.name}\n  source: https://archive.org/details/{ident}\n  license: {lic}\n"
            )
            print(f"    OK ({dur:.0f}s) → {dest.name}  [{got}/{per_mood}]")

    if credits:
        cred_file = folder / "CREDITS.txt"
        prev = cred_file.read_text(encoding="utf-8") if cred_file.exists() else ""
        cred_file.write_text(
            prev + "\n".join(credits) + "\n", encoding="utf-8"
        )
    return credits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-mood", type=int, default=4)
    args = ap.parse_args()

    total = 0
    for mood, queries in MOOD_QUERIES.items():
        total += len(fetch_mood(mood, queries, args.per_mood))

    print(f"\nDone. Downloaded {total} new tracks.")
    for mood in MOOD_QUERIES:
        folder = MUSIC_DIR / mood
        tracks = [p.name for p in folder.iterdir() if p.suffix.lower() in (".mp3", ".ogg")]
        print(f"  {mood}: {len(tracks)} tracks")
    sys.exit(0)


if __name__ == "__main__":
    main()
