# Background Music Library (per-mood)

> **Bundled tracks**: each folder ships with public-domain/CC0 tracks pulled from
> archive.org netlabel collections via `python scripts/fetch_music.py` — see the
> `CREDITS.txt` in each folder for source + license. Add or swap tracks any time;
> the pipeline picks randomly per video. The per-mood **visual color grade** uses
> the same mood mapping, so a channel's look and sound stay consistent.

The pipeline picks ONE random track per video from the mood folder mapped to the channel:

| Folder | Channels | Feel |
|---|---|---|
| `dark_mystery/` | Restricted Lore, Covered Pages, Filed And Forgotten | low dark ambient drone, investigation pulse |
| `eerie_horror/` | The Cursed Map, Myth Bleed | unsettling atmosphere, distant choirs, horror pads |
| `epic_history/` | Blade Archives, Erased Lore, Ruined Clock | slow epic percussion, war drums, ancient strings |
| `tense_science/` | Fracture Layer, Classified Cognition | tense minimal electronic pulse, ticking synths |

If a folder is empty the pipeline falls back to `assets/background.mp3`, so nothing breaks.

## Track requirements
- 3–6 tracks per folder, each **≥ 60 seconds**, `.mp3` (or wav/m4a/ogg/flac)
- Instrumental only — no vocals (they fight the voiceover)
- Loudness does NOT matter — the pipeline normalizes the final mix to −14 LUFS and ducks music under the voice automatically

## Where to download (FREE + safe for a PUBLIC repo)
This repo is public, so only use **true CC0 / public-domain** sources that allow redistribution:

- **FreePD.com** — all public domain (CC0). Categories: "Horror", "Epic", "Scoring".
- **OpenGameArt.org** — filter license = CC0. Search: "dark ambient", "horror loop", "epic battle".
- **Pixabay Music** — ONLY tracks explicitly marked CC0/public domain.

⚠️ Do NOT use the YouTube Audio Library here — its license does not allow redistributing the files in a repo.

## Suggested search terms per mood
- dark_mystery → "dark ambient drone", "mystery investigation", "suspense underscore"
- eerie_horror → "horror atmosphere", "creepy ambient", "haunted drone"
- epic_history → "epic war percussion", "ancient battle drums", "cinematic history"
- tense_science → "tense pulse", "minimal electronic suspense", "ticking tension"
