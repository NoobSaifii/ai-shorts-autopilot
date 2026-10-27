import logging
import re
from typing import List

from faster_whisper import WhisperModel

logger = logging.getLogger("pipeline.captions")

# Load model globally to avoid reloading on every scene
# We use 'base' for speed — it supplies word TIMINGS only; the displayed words
# come from the known scene_text, so transcription typos can't reach the screen.
_model = None

# Words that get the accent color + larger size (match the channels' prompt laws)
POWER_WORDS = {
    "erased", "buried", "classified", "vanished", "suppressed", "deleted",
    "rewritten", "sealed", "redacted", "exposed", "banned", "forbidden",
    "secret", "secrets", "hidden", "never", "impossible", "lie", "lies",
    "killed", "death", "dead", "cursed", "haunted", "destroyed", "stolen",
    "silenced", "censored", "untouched", "lost", "warning",
}

_DEFAULT_ACCENT = "&H0000D7FF"  # gold


def get_whisper_model():
    global _model
    if _model is None:
        logger.info("Loading Whisper model for word-level captions...")
        # device="cuda" if available, else "cpu"
        _model = WhisperModel("base", device="cpu", compute_type="int8")
    return _model


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS time format: H:MM:SS.cs"""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_color_tag(color: str) -> str:
    """'&H0000FFFF' / '&HFFFF00' → override-tag form '&H0000FFFF&' (BBGGRR)."""
    hexpart = re.sub(r"[^0-9A-Fa-f]", "", color or "")
    if len(hexpart) >= 6:
        hexpart = hexpart[-6:]
    else:
        hexpart = "00D7FF"
    return f"&H00{hexpart}&"


def _ass_color_style(color: str) -> str:
    """Same, but full 8-digit AABBGGRR form for the [V4+ Styles] section."""
    hexpart = re.sub(r"[^0-9A-Fa-f]", "", color or "")
    if len(hexpart) >= 6:
        hexpart = hexpart[-6:]
    else:
        hexpart = "00D7FF"
    return f"&H00{hexpart}"


def _display_word(word: str) -> str:
    """UPPERCASE, strip sentence punctuation that looks noisy on screen."""
    return word.strip().strip(".,;:").upper()


def _fmt_word(word: str, accent_tag: str, highlight: bool, emphasis: set = None) -> str:
    """Render one word with optional accent highlight / power-word pop.
    Director-Mode `emphasis` words (model-chosen) always get the accent pop."""
    bare = re.sub(r"[^A-Za-z']", "", word).lower()
    shown = _display_word(word)
    if not shown:
        return ""
    if bare in POWER_WORDS or (emphasis and bare in emphasis):
        return f"{{\\c{accent_tag}\\fs126}}{shown}{{\\fs112\\c&H00FFFFFF&}}"
    if highlight:
        return f"{{\\c{accent_tag}}}{shown}{{\\c&H00FFFFFF&}}"
    return shown


def _phrase_text(phrase_words: list, active_idx: int, accent_tag: str, emphasis: set) -> str:
    """Render a whole on-screen phrase with the currently-spoken word highlighted
    (karaoke). Active word = accent + quick scale-pop (returns to 100% so the line
    doesn't permanently reflow). POWER/emphasis words stay accent throughout."""
    parts = []
    for k, w in enumerate(phrase_words):
        shown = _display_word(w)
        if not shown:
            continue
        bare = re.sub(r"[^A-Za-z']", "", w).lower()
        is_emph = bare in POWER_WORDS or (emphasis and bare in emphasis)
        if k == active_idx:
            parts.append(
                f"{{\\c{accent_tag}\\fscx118\\fscy118\\t(0,90,\\fscx100\\fscy100)}}"
                f"{shown}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}"
            )
        elif is_emph:
            parts.append(f"{{\\c{accent_tag}}}{shown}{{\\c&H00FFFFFF&}}")
        else:
            parts.append(shown)
    return " ".join(parts)


def generate_hormozi_ass(
    audio_path: str,
    output_ass_path: str,
    scene_text: str = "",
    accent_color: str = _DEFAULT_ACCENT,
    hook_text: str = "",
    font_name: str = "Anton",
    emphasis_words: list = None,
):
    """
    Word-level pop-up ASS subtitles (Hormozi style) from TTS audio.

    Whisper supplies word TIMINGS; the displayed words come from scene_text
    when the word counts line up (fixes mis-transcribed names). Captions sit
    lower-center (~66% height) so they never cover the subject's focal point.
    hook_text (scene 1 only) renders as a top-center stamp for ~1.8s.
    """
    model = get_whisper_model()
    segments, info = model.transcribe(audio_path, word_timestamps=True)

    accent_tag = _ass_color_tag(accent_color)
    accent_style = _ass_color_style(accent_color)

    # Build the emphasis lookup, splitting multi-word phrases (e.g. a spelled-out
    # year "fifteen eighteen") into individual words so each one matches on screen.
    emphasis_set = set()
    for w in (emphasis_words or []):
        for part in str(w).split():
            bare = re.sub(r"[^A-Za-z']", "", part).lower()
            if bare:
                emphasis_set.add(bare)

    ass_content = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font_name},112,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0.5,0,1,7,2,2,60,60,640,1",
        f"Style: Hook,{font_name},116,{accent_style},&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,1,0,1,8,3,8,50,50,210,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    timed_words = []
    for segment in segments:
        for word in segment.words:
            timed_words.append(word)

    # Swap in the KNOWN script words. If counts mismatch, distribute script words
    # proportionally across the whisper timings to strictly enforce Roman script.
    display_words: List[str] = [w.word for w in timed_words]
    script_words = (scene_text or "").split()
    
    if script_words:
        if len(script_words) == len(timed_words):
            display_words = script_words
        else:
            logger.debug(
                f"caption word count mismatch (whisper={len(timed_words)} "
                f"script={len(script_words)}) — mapping to enforce Roman script"
            )
            display_words = []
            for i in range(len(timed_words)):
                start_s = int(round(i * len(script_words) / len(timed_words)))
                end_s = int(round((i + 1) * len(script_words) / len(timed_words)))
                display_words.append(" ".join(script_words[start_s:end_s]))

    # ── Word-by-word karaoke ──────────────────────────────────────────────────
    # Show ~3 words per screen (a "phrase"); within each phrase emit one event
    # per word so the currently-spoken word highlights and moves across the line.
    CHUNK = 3
    n = len(timed_words)
    i = 0
    while i < n:
        chunk = list(range(i, min(i + CHUNK, n)))
        phrase_words = [display_words[k] for k in chunk]
        for pos, k in enumerate(chunk):
            start = timed_words[k].start
            end = timed_words[k + 1].start if (k + 1) < n else timed_words[k].end
            if end <= start:
                end = start + 0.18
            text = _phrase_text(phrase_words, pos, accent_tag, emphasis_set)
            if not text.strip():
                continue
            # soft fade-in only on the first word of the phrase
            lead = "{\\fad(70,0)}" if pos == 0 else ""
            ass_content.append(
                f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},Cap,,0,0,0,,{lead}{text}"
            )
        i += CHUNK

    # Scene-1 hook stamp: big top-center headline, bounce-in, ~first 2.2s
    if hook_text.strip():
        stamp = hook_text.strip().upper()
        hook_anim = (
            "{\\fad(150,300)\\fscx70\\fscy70"
            "\\t(0,220,\\fscx106\\fscy106)\\t(220,360,\\fscx100\\fscy100)}"
        )
        ass_content.append(
            f"Dialogue: 1,{format_ass_time(0.05)},{format_ass_time(2.2)},Hook,,0,0,0,,{hook_anim}{stamp}"
        )

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ass_content))

    logger.info(f"Generated Hormozi captions -> {output_ass_path}")
