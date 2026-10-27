"""Free local audio asset selection: per-mood music + timed SFX events.

Folders (all optional — everything degrades gracefully):
    assets/music/<mood>/*.mp3     mood = dark_mystery | eerie_horror | epic_history | tense_science
    assets/sfx/boom/*.mp3         deep cinematic hit (scene 1)
    assets/sfx/whoosh/*.mp3       short transition swipe (energy jumps)
    assets/sfx/riser/*.mp3        2-4s build into the final scene
    assets/sfx/heartbeat/*.mp3    optional, off by default
"""

import logging
import random
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("pipeline.audio_assets")

_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac")

# Fallback channel→mood map for configs that predate the music_mood key
# (e.g. a stale CONFIG_YAML_B64 secret in CI).
CHANNEL_MOOD = {
    "Restricted Lore":       "dark_mystery",
    "Covered Pages":         "dark_mystery",
    "Filed And Forgotten":   "dark_mystery",
    "The Cursed Map":        "eerie_horror",
    "Myth Bleed":            "eerie_horror",
    "Blade Archives":        "epic_history",
    "Erased Lore":           "epic_history",
    "Ruined Clock":          "epic_history",
    "Fracture Layer":        "tense_science",
    "Classified Cognition":  "tense_science",
}

DEFAULT_MOOD = "dark_mystery"


def _audio_files(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in _AUDIO_EXTS)


def resolve_mood(channel_name: str, configured_mood: str = "") -> str:
    if configured_mood:
        return configured_mood
    return CHANNEL_MOOD.get(channel_name, DEFAULT_MOOD)


def pick_music(
    mood: str,
    music_dir: str,
    fallback_path: str = "",
    seed: str = "",
) -> Optional[str]:
    """Random track from assets/music/<mood>/, seeded for resume determinism.
    Empty/missing folder → fallback_path → None (skip music)."""
    candidates = _audio_files(Path(music_dir) / mood)
    if not candidates:
        # Any track from any mood folder is still better than the legacy single file
        candidates = _audio_files(Path(music_dir))
    if candidates:
        rng = random.Random(seed or None)
        chosen = str(rng.choice(candidates))
        logger.info(f"music[{mood}]: {Path(chosen).name}")
        return chosen
    if fallback_path and Path(fallback_path).is_file():
        logger.info(f"music[{mood}]: folder empty — fallback {Path(fallback_path).name}")
        return fallback_path
    logger.warning(f"music[{mood}]: no tracks and no fallback — video will have no music")
    return None


def pick_sfx(kind: str, sfx_dir: str, seed: str = "") -> Optional[str]:
    candidates = _audio_files(Path(sfx_dir) / kind)
    if not candidates:
        return None
    rng = random.Random(f"{seed}:{kind}" if seed else None)
    return str(rng.choice(candidates))


def _normalize_energy(energy: str) -> str:
    e = str(energy or "").strip().lower()
    if e in ("max", "maximum", "very high", "extreme"):
        return "maximum"
    if e in ("low", "medium", "high"):
        return e
    return "medium"


_ENERGY_RANK = {"low": 0, "medium": 1, "high": 2, "maximum": 3}


_SFX_DEFAULT_VOL = {"boom": 0.40, "whoosh": 0.22, "riser": 0.25, "heartbeat": 0.18}
_SFX_ALIASES = {
    "boom": "boom", "impact": "boom", "hit": "boom", "drop": "boom", "thud": "boom",
    "whoosh": "whoosh", "swoosh": "whoosh", "swipe": "whoosh", "transition": "whoosh",
    "riser": "riser", "rise": "riser", "build": "riser", "sweep": "riser",
    "heartbeat": "heartbeat", "heart": "heartbeat", "pulse": "heartbeat",
}

# Volume per SFX category (folder name). Anything else → default.
_SFX_CATEGORY_VOL = {"boom": 0.36, "whoosh": 0.26, "riser": 0.24, "heartbeat": 0.16}


def _all_sfx_files(sfx_dir: str) -> List[Path]:
    """Every audio file anywhere under assets/sfx/ (all categories pooled)."""
    base = Path(sfx_dir)
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*") if p.suffix.lower() in _AUDIO_EXTS)


def build_random_sfx_timeline(
    scene_starts: List[float],
    sfx_dir: str,
    seed: str = "",
) -> List[Tuple[float, str, float]]:
    """ONE randomly-chosen SFX per scene, drawn from the whole assets/sfx/ pool,
    placed right at each scene's cut. Deterministic per video (seeded by title)
    and avoids repeating the immediately previous sound. Returns [] if the
    folder has no audio files."""
    pool = _all_sfx_files(sfx_dir)
    if not pool or not scene_starts:
        return []

    events: List[Tuple[float, str, float]] = []
    prev = None
    for i, t in enumerate(scene_starts):
        rng = random.Random(f"{seed}:{i}")
        choices = [p for p in pool if p != prev] or pool
        chosen = rng.choice(choices)
        prev = chosen
        vol = _SFX_CATEGORY_VOL.get(chosen.parent.name.lower(), 0.25)
        events.append((max(t - 0.08, 0.0), str(chosen), vol))

    logger.info(
        f"random sfx: 1 cue per scene × {len(events)} scenes, "
        f"chosen from {len(pool)} files in {sfx_dir}"
    )
    return events


def build_director_sfx_timeline(
    scene_starts: List[float],
    scene_sfx: List[str],
    sfx_dir: str,
    seed: str = "",
    max_events: int = 9,
    min_spacing: float = 3.0,
) -> List[Tuple[float, str, float]]:
    """Model-authored SFX: each scene may name a sound (boom/whoosh/riser/
    heartbeat). Placed at that scene's start with sensible volume + safety
    clamps (max count, min spacing). Returns [] when the model named none."""
    events: List[Tuple[float, str, float]] = []
    last_t = -999.0
    for i, raw in enumerate(scene_sfx):
        if i >= len(scene_starts):
            break
        kind = _SFX_ALIASES.get(str(raw or "").strip().lower(), "")
        if not kind:
            continue
        t = scene_starts[i]
        if t - last_t < min_spacing and kind != "boom":
            continue
        f = pick_sfx(kind, sfx_dir, f"{seed}:{i}")
        if not f:
            continue
        events.append((max(t - 0.10, 0.0), f, _SFX_DEFAULT_VOL.get(kind, 0.22)))
        last_t = t
        if len(events) >= max_events:
            break
    if events:
        logger.info(
            "director sfx: "
            + ", ".join(f"{t:.1f}s {Path(f).parent.name}@{v:g}" for t, f, v in events)
        )
    return events


def build_sfx_timeline(
    scene_durations: List[float],
    scene_energies: List[str],
    sfx_dir: str,
    seed: str = "",
    use_heartbeat: bool = False,
) -> List[Tuple[float, str, float]]:
    """Sound-design event list (time_s, file, volume) for the final mix.

    - deep boom under the scene-1 hook
    - whoosh on cuts where energy jumps up (max 6, min 6s apart)
    - riser leading into the final scene
    """
    events: List[Tuple[float, str, float]] = []
    if not scene_durations:
        return events

    boom = pick_sfx("boom", sfx_dir, seed)
    if boom:
        events.append((0.05, boom, 0.40))

    # Scene start times
    starts = []
    t = 0.0
    for d in scene_durations:
        starts.append(t)
        t += max(d, 0.0)
    total = t

    energies = [_normalize_energy(e) for e in scene_energies]
    while len(energies) < len(scene_durations):
        energies.append("medium")

    whoosh_count = 0
    last_whoosh = -10.0
    for i in range(1, len(scene_durations)):
        if whoosh_count >= 6:
            break
        prev_rank = _ENERGY_RANK[energies[i - 1]]
        cur_rank = _ENERGY_RANK[energies[i]]
        if cur_rank > prev_rank and cur_rank >= 2:  # jump up into high/maximum
            cut = starts[i]
            if cut - last_whoosh >= 6.0:
                whoosh = pick_sfx("whoosh", sfx_dir, f"{seed}:{i}")
                if not whoosh:
                    break
                events.append((max(cut - 0.15, 0.0), whoosh, 0.22))
                last_whoosh = cut
                whoosh_count += 1

    if len(scene_durations) >= 3:
        riser = pick_sfx("riser", sfx_dir, seed)
        if riser:
            riser_at = max(starts[-1] - 2.0, 0.0)
            events.append((riser_at, riser, 0.25))

    if use_heartbeat:
        hb = pick_sfx("heartbeat", sfx_dir, seed)
        if hb and total > 12:
            events.append((max(total - 10.0, 0.0), hb, 0.18))

    events.sort(key=lambda e: e[0])
    if events:
        logger.info(
            "sfx timeline: "
            + ", ".join(f"{t:.1f}s {Path(f).parent.name}@{v:g}" for t, f, v in events)
        )
    else:
        logger.info("sfx timeline: no SFX assets found — skipping sound design layer")
    return events
