import asyncio
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import httpx

logger = logging.getLogger("pipeline.script_gen")

GEMINI_PROMPT_TEMPLATE = """You are a dark history writer and viral short-video architect for 'Restricted Lore' targeting English-speaking audiences in the US, UK, Canada, and Australia.

RETURN ONLY VALID JSON. No markdown. No backticks. No text outside the JSON.

INPUTS: Series: {series_name} | Episode: {episode_no} | Topic: {topic}

OUTPUT:
{{
  "title": "3-6 word Netflix-style English title, folder-safe",
  "script_rewritten": "130-160 word full script block",
  "scenes": [{{"scene_no": 1, "scene_text": "10-14 words", "image_prompt": "...", "motion": "keyword", "duration": 2, "scene_energy": "high"}}]
}}

━━━ NUMBERS LAW — ABSOLUTE, NO EXCEPTIONS ━━━
Every number in script_rewritten and scene_text = full spoken English words. No digits. No numerals.
200,000 → two hundred thousand | 1848 → eighteen forty-eight | 30 feet → thirty feet | $500B → five hundred billion dollars | 16th century → sixteenth century
Scan every character before output. Digit found = rewrite immediately.

━━━ SCRIPT: 130-160 WORDS ━━━
VOICE: Calm investigator reading a suppressed file. Cold facts. No filler. Max twelve words per sentence. Simple enough for a fourteen year old.
FORBIDDEN PHRASES: some believe / theorists claim / perhaps / maybe / could be / might have / allegedly / according to some — speak every fact as confirmed truth.
Every sentence must contain one real fact: a real year in words, name, place, or document.

SIX-PART STRUCTURE — IN ORDER:

[1] HOOK (2-3 sentences)
Before writing: extract the single most impossible, personally-threatening fact about THIS topic specifically.
First word chosen by what the topic DEMANDS — not randomly from a list.
BANNED openers: 'They buried' / 'They erased' / 'They hid' — too generic. Name a specific number, place, object, or direct viewer threat.
Hook must make viewer feel: this threatens ME right now.
Examples: 'Three real cities sit beneath your ocean right now. No one told you.' | 'One kingdom held more gold than every bank on Earth today. It was cut from every map you ever saw.'

[2] CONTEXT BRIDGE (3-4 sentences)
Assume zero viewer knowledge. Answer: What is it? Where exactly? How big/powerful? When? Why never heard of it?
MODERN COMPARISON LAW: Every size/power/wealth claim must compare to something viewer knows today with a specific number in words.
Examples: 'bigger than the US and Canada combined — eleven million square miles' | 'more gold than Elon Musk and Bezos combined, multiplied by ten' | 'more people than modern Tokyo — over thirty million'

[3] STAKES (2 sentences) — Why this matters today. Their reality is built on a lie.

[4] EVIDENCE — Real names. Real years in words. Real locations. One real document or declassified file named. Explain it in plain words.

[5] COVER-UP — What was hidden? Who? Why? Simple cause-and-effect.

[6] CLIFFHANGER — One personal question. Makes stopping impossible.

━━━ SCENES: EXACTLY 25-30 ━━━
One visual idea per scene. Order follows script exactly. No repeated compositions.
Split any line over fourteen words across 2-3 scenes.

PACING:
Scenes 1-8: duration 1.5-2.5s, energy high→medium (Hook + Context)
Scenes 9-20: duration 2-3s, energy medium→high (Evidence + Cover-up)
Scenes 21-30: duration 2.5-3.5s, energy low→maximum (Paranoia + Cliffhanger)

SCENE_TEXT RULES:
— 10 to 14 words. Hard limit.
— Every number = full spoken words. No digits.
— Must contain one real name, date in words, place, or document.
— Include modern comparison with number in words when covering size/wealth/power.
— End with tension or revelation.
— Forbidden: passive voice, filler openers, any digit.
POWER WORDS: erased / buried / classified / vanished / suppressed / deleted / rewritten / sealed / redacted / exposed

━━━ SCENE 1 IMAGE — MAXIMUM IMPACT ━━━
This is the most important image in the video. Before writing it:
Step 1 — Identify the single most impossible physical fact from the script about this topic.
Step 2 — That fact becomes Layer 6. The entire image must be built around topic DNA.

BUILD ALL 7 LAYERS — NO LAYER SKIPPED:

L1 SUBJECT ANCHOR: Most iconic physical object of this episode at frame center. Hyper-realistic micro-detail — every crack, texture, imperfection. Must feel tangible.

L2 ENVIRONMENT: Fully realized setting 100% specific to this topic — exact location, culture, period. Minimum five named distinct objects from this topic in background.

L3 ATMOSPHERE — three simultaneously, each physically interacting with subject:
Choose 3: bioluminescence / electric arc glow / fire ember particles / water droplets mid-air / dust motes in god-ray / sparks shower / smoke tendrils / ground mist / heat shimmer / ash fall

L4 LIGHTING — name all three:
Key light: color + direction + surface it strikes
Fill light: color + how it softens shadows
Rim light: color + how it separates subject from background
Mood: forbidden discovery — viewer is first person to ever see this.

L5 CAMERA: extreme close-up or first-person POV only (no mid-range). Lens: 14mm ultra-wide or macro 1:1. Aperture f/1.4. Dutch tilt max fifteen degrees.

L6 IMPOSSIBLE DETAIL — TOPIC-DNA LAW:
NOT a horror cliche. Derived from the actual script evidence — the most impossible physical state of real evidence from this topic. Viewer half-recognizes it but knows it cannot exist as shown. Describe precisely.

L7 COLOR GRADE — most dramatic in episode. Choose one:
blood orange with deep black / ice blue with crimson / bone white with slate charcoal / deep teal with amber / electric blue with gold
Color grade bleeds into every surface — subject, environment, atmosphere, light.

SCENE 1 QUALITY HEADER — always include verbatim:
'masterpiece, best quality, ultra realistic, highly detailed, ARRI Alexa LF cinematic, 8K, shallow depth of field, volumetric god-rays, photorealistic, National Geographic documentary grade, no CGI toy aesthetic, no text overlays, no watermarks, portrait orientation 9:16'

━━━ SCENE 2 OR 3 — ORIENTATION ━━━
Answers: 'What am I watching?' Scene_text includes modern size comparison with number in words. Image shows topic at maximum geographical or physical scale.

━━━ ALL OTHER SCENE IMAGE PROMPTS ━━━
Build in order:
1. 'masterpiece, best quality, ultra realistic, highly detailed, ARRI Alexa LF cinematic, 8K, shallow depth of field, volumetric god-rays, photorealistic'
2. 'vertical 9:16 mobile frame, subject centered in upper two-thirds'
3. Subject: exact texture, color, material, pose, surface detail
4. Environment: exact location, time, weather, season — foreground/mid/background
5. Lighting: key + fill + rim, shadow depth, bloom
6. CINEMATIC LAYER — one per scene, never repeat within three consecutive scenes:
bioluminescence / electric arc glow / fire ember particles / water droplets mid-air / dust motes in god-ray / pollen float / sparks shower / smoke tendrils / ground mist / heat shimmer / frozen breath cloud / ash fall
7. COLOR GRADE — one per scene, always vary:
deep teal with amber / electric blue with gold / blood orange with deep black / emerald with violet / ice blue with crimson / bone white with slate charcoal / rust orange with midnight blue
8. Camera: lens type + shot type + aperture + motion state
9. Engagement hook: one detail that makes this image impossible to ignore

COMPOSITION LAW: Each scene must differ from last three in ALL of: shot type, lighting color, cinematic layer. Any match = redesign.
HARD RULES: no text overlays / no stock compositions / BBC or NatGeo realism / no CGI toy aesthetic / single quotes only inside prompts — never double quotes.

━━━ IMAGE SAFETY LAW — CLOUDFLARE 3030 PREVENTION ━━━
NEVER write any real person's name inside image_prompt. Describe physically instead.
NEVER name any brand, franchise, film, or show inside image_prompt. Describe generically.
MANDATORY SUFFIX on every image_prompt: ', no real people, no brand logos, no copyrighted characters, artistic interpretation only'

━━━ FINAL SELF-CHECK ━━━
1. Any digit in scene_text or script? → convert to words
2. Scene 1 hook names something SPECIFIC — not a banned generic opener?
3. Scene 1 impossible detail derived from actual script evidence — not a cliche?
4. Every scene_text between ten and fourteen words?
5. All compositions differ in shot type, lighting, cinematic layer?
6. Any real person name or brand in any image_prompt? → replace with physical description
Fail any check → rewrite before output."""


def _safe_title(raw: str) -> str:
    english_only = re.sub(r"[^A-Za-z ]", "", raw)
    return re.sub(r"_+", "_", re.sub(r"\s+", "_", english_only.strip())).strip("_") or "Untitled_Project"


# Word-to-number lookup used by _parse_duration and _parse_scene_no
_WORD_TO_INT = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "twenty-one": 21, "twenty-two": 22,
    "twenty-three": 23, "twenty-four": 24, "twenty-five": 25,
    "twenty-six": 26, "twenty-seven": 27, "twenty-eight": 28,
    "twenty-nine": 29, "thirty": 30, "half": 0,
}


def _parse_duration(val, default: float = 2.0) -> float:
    """
    Parse scene duration that Gemini may return as a float OR as English words.
    Examples: 2.5 → 2.5 | "2.5" → 2.5 | "one point five" → 1.5 | "two" → 2.0
    """
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    # Direct numeric string
    try:
        return float(s)
    except ValueError:
        pass
    # "X point Y" pattern  e.g. "one point five" → 1.5
    if "point" in s:
        parts = s.split("point", 1)
        int_word  = parts[0].strip()
        frac_word = parts[1].strip()
        int_val  = _WORD_TO_INT.get(int_word, None)
        frac_val = _WORD_TO_INT.get(frac_word, None)
        if int_val is not None and frac_val is not None:
            return float(int_val) + frac_val / 10.0
    # Simple single word e.g. "two" → 2.0
    if s in _WORD_TO_INT:
        return float(_WORD_TO_INT[s])
    logger.warning(f"Could not parse duration '{val}' — defaulting to {default}")
    return default


def _parse_scene_no(val, default: int = 0) -> int:
    """
    Parse scene_no that Gemini may return as int OR English word.
    Examples: 5 → 5 | "five" → 5 | "twenty-three" → 23
    """
    if isinstance(val, int):
        return val
    s = str(val).strip().lower()
    try:
        return int(float(s))
    except ValueError:
        pass
    if s in _WORD_TO_INT:
        return _WORD_TO_INT[s]
    logger.warning(f"Could not parse scene_no '{val}' — defaulting to {default}")
    return default


@dataclass
class Scene:
    scene_no: int
    scene_text: str
    image_prompt: str
    voice_text: str = ""
    motion: str = "cinematic_push"
    duration: float = 2.0
    scene_energy: str = "medium"
    transition_to_next: str = ""
    # ── Director Mode (model-authored editing instructions) ──────────────────
    voice_tone: str = "neutral"        # whisper/intense/ominous/urgent/somber/awe/...
    sfx: str = ""                      # boom/whoosh/riser/heartbeat/"" — placed at scene start
    emphasis_words: List[str] = field(default_factory=list)  # words to accent in captions
    graphic: dict = field(default_factory=dict)  # motion-graphic overlay: {type, title, subtitle}


@dataclass
class ScriptResult:
    title: str
    script_rewritten: str
    viral_title: str = ""
    short_description: str = ""
    hashtags: List[str] = field(default_factory=list)
    scenes: List[Scene] = field(default_factory=list)
    hook_text: str = ""             # 3-5 word on-screen stamp for scene 1 overlay
    engagement_question: str = ""   # comment-bait question for the description
    thumbnail_prompt: str = ""      # dedicated object-rich image prompt for the thumbnail
    thumbnail_text: str = ""        # 2-4 word punchy headline overlaid on the thumbnail
    thumbnail_keyword: str = ""     # the one word shown in the accent highlight box


GRAPHIC_TYPES = ("date_stamp", "stat_counter", "name_card", "quote_card", "chapter_title")
MAX_GRAPHICS = 5

# Shared by every channel prompt (appended after .format(), so braces are literal).
GRAPHICS_ADDENDUM = """

MOTION GRAPHICS — REQUIRED: exactly 3 to 5 scene objects MUST carry an extra key "graphic".
Pick scenes (never scene 1) where an on-screen card makes a real fact land, and add to that scene object:
  "graphic": {"type": "<one type>", "title": "...", "subtitle": "..."}
Types:
  date_stamp    — title = the year or date as digits ("1258", "14 March 1883"), subtitle = the place
  stat_counter  — title = ONE number as digits only ("40000"), subtitle = what it counts (2-5 words)
  name_card     — title = the person's real name, subtitle = who they were (2-6 words)
  quote_card    — title = a short real quote or decree (max 10 words), subtitle = who said it
  chapter_title — title = 2-4 word chapter heading for a turn in the story, subtitle = ""
Rules: every fact on a card must already be stated in the narration; never invent numbers or quotes.
Card text uses the same alphabet as scene_text (digits allowed here even where narration spells numbers).
Use each type at most twice. Scenes without a card simply omit "graphic".
Before returning, count the scenes that have "graphic": fewer than 3 means the JSON is not finished.
"""


def _parse_graphic(raw, scene_no: int) -> dict:
    if not isinstance(raw, dict) or scene_no <= 1:
        return {}
    gtype = str(raw.get("type", "")).strip().lower()
    title = str(raw.get("title", "")).strip()
    if gtype not in GRAPHIC_TYPES or not title:
        return {}
    if gtype == "stat_counter" and not re.fullmatch(r"\d{1,9}", title.replace(",", "")):
        return {}
    return {"type": gtype, "title": title[:60], "subtitle": str(raw.get("subtitle", "")).strip()[:60]}


def _load_prompt(channel: str) -> str:
    prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
    prompt_file = prompts_dir / f"{channel}.txt"
    if not prompt_file.exists():
        prompt_file = prompts_dir / "Restricted Lore.txt"
        logger.info(f"No prompt file for channel '{channel}' — using Restricted Lore fallback")
    return prompt_file.read_text(encoding="utf-8")


def _resolve_key(provider: dict) -> str:
    """Provider key from explicit value or an environment variable (CI)."""
    key = str(provider.get("api_key", "")).strip()
    if key.startswith("env:"):
        return os.environ.get(key[4:], "").strip()
    if not key and provider.get("api_key_env"):
        return os.environ.get(provider["api_key_env"], "").strip()
    return key


async def _post_with_retry(client, url, headers, payload, attempts, tag):
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            if attempt == attempts:
                logger.warning(f"[{tag}] failed {attempts}x: {str(e)[:160]}")
                return None
            delay = 2 ** attempt
            logger.warning(f"[{tag}] attempt {attempt}/{attempts}: {str(e)[:120]} — retry {delay}s")
            await asyncio.sleep(delay)
    return None


async def _call_anthropic_compat(client, provider, gen, prompt_text) -> Optional[str]:
    """Anthropic Messages API (also AgentRouter and other gateways).
    Returns the raw model text, or None on failure."""
    base = str(provider.get("base_url", "https://api.anthropic.com")).rstrip("/")
    model = provider.get("model", "claude-opus-4-6")
    key = _resolve_key(provider)
    if not key:
        logger.warning(f"[anthropic:{model}] no api_key — skipping provider")
        return None
    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        **(provider.get("headers") or {}),
    }
    payload = {
        "model": model,
        "max_tokens": int(provider.get("max_tokens", 8192)),
        "temperature": gen["temperature"],
        "messages": [{"role": "user", "content": prompt_text}],
    }
    resp = await _post_with_retry(
        client, f"{base}/v1/messages", headers, payload,
        int(provider.get("attempts", 3)), f"anthropic:{model}",
    )
    if resp is None:
        return None
    data = resp.json()
    return "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text")


async def _call_openai_compat(client, provider, gen, prompt_text) -> Optional[str]:
    """OpenAI Chat Completions API (also OpenRouter / compatible gateways)."""
    base = str(provider.get("base_url", "https://api.openai.com")).rstrip("/")
    model = provider.get("model", "gpt-4o")
    key = _resolve_key(provider)
    if not key:
        logger.warning(f"[openai:{model}] no api_key — skipping provider")
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        **(provider.get("headers") or {}),
    }
    payload = {
        "model": model,
        "max_tokens": int(provider.get("max_tokens", 8192)),
        "temperature": gen["temperature"],
        "messages": [{"role": "user", "content": prompt_text}],
    }
    resp = await _post_with_retry(
        client, f"{base}/v1/chat/completions", headers, payload,
        int(provider.get("attempts", 3)), f"openai:{model}",
    )
    if resp is None:
        return None
    data = resp.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


async def _call_gemini(client, provider, gen, prompt_text, keys) -> Optional[str]:
    """Google Gemini generateContent across the key pool, with a model
    priority list (better model first, cheap try; last model = deep retry)."""
    model_list = [m for m in (provider.get("models") or []) if m] or [provider.get("model", "gemini-2.5-flash")]
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": gen["temperature"],
            "topP": gen["top_p"],
            "topK": gen["top_k"],
            "maxOutputTokens": 16384,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0}
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    for i, model in enumerate(model_list):
        is_last = i == len(model_list) - 1
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        use_keys = keys if is_last else keys[:8]
        attempts = 5 if is_last else 2
        for key in use_keys:
            headers = {"Content-Type": "application/json", "x-goog-api-key": key}
            resp = await _post_with_retry(client, url, headers, payload, attempts, f"gemini:{model}")
            if resp is not None:
                data = resp.json()
                candidate = data.get("candidates", [{}])[0]
                logger.info(f"Gemini Finish Reason: {candidate.get('finishReason')} | Tokens: {data.get('usageMetadata')}")
                if candidate.get("finishReason") != "STOP":
                    logger.error(f"Gemini output truncated. Full data: {json.dumps(data, indent=2)}")
                text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
                if text:
                    return text
        if not is_last:
            logger.warning(f"Gemini model {model} unavailable — next model")
    return None


def _load_gemini_keys(api_key: str) -> List[str]:
    keys = []
    keys_file = Path(__file__).resolve().parent.parent / "gemini_keys.txt"
    if keys_file.exists():
        keys = [k.strip() for k in keys_file.read_text().splitlines() if k.strip()]
    if not keys and api_key:
        keys = [api_key]
    if not keys:
        return []
    # Round-robin: each channel call starts from the next key so no single key
    # is hammered across channels, avoiding a 429 cascade.
    idx_file = Path(tempfile.gettempdir()) / "gemini_key_index.txt"
    try:
        start = int(idx_file.read_text().strip()) % len(keys)
    except Exception:
        start = 0
    try:
        idx_file.write_text(str((start + 1) % len(keys)))
    except Exception:
        pass
    return keys[start:] + keys[:start]


async def generate_script(
    series_name: str,
    episode_no: int,
    topic: str,
    channel: str,
    api_key: str,
    model: str = "gemini-2.0-flash",
    temperature: float = 0.95,
    top_p: float = 0.95,
    top_k: int = 40,
    models: list = None,
    llm_config: dict = None,
) -> ScriptResult:
    template = _load_prompt(channel)
    prompt_text = template.format(
        series_name=series_name,
        episode_no=episode_no,
        topic=topic,
    ) + GRAPHICS_ADDENDUM

    gen = {
        "temperature": float((llm_config or {}).get("temperature", temperature)),
        "top_p": float((llm_config or {}).get("top_p", top_p)),
        "top_k": int((llm_config or {}).get("top_k", top_k)),
    }

    # Provider chain: try each in order (e.g. Claude first, Gemini fallback).
    # If no llm.providers configured, fall back to the legacy Gemini-only path.
    providers = list((llm_config or {}).get("providers") or [])
    if not providers:
        providers = [{"type": "gemini", "api_key": api_key, "models": models or [model]}]

    gemini_keys = _load_gemini_keys(api_key)

    text = ""
    async with httpx.AsyncClient(timeout=240.0) as client:
        for provider in providers:
            ptype = str(provider.get("type", "gemini")).lower()
            try:
                if ptype in ("anthropic", "anthropic_compat", "claude"):
                    text = await _call_anthropic_compat(client, provider, gen, prompt_text)
                elif ptype in ("openai", "openai_compat"):
                    text = await _call_openai_compat(client, provider, gen, prompt_text)
                else:
                    text = await _call_gemini(client, provider, gen, prompt_text, gemini_keys)
            except Exception as e:
                logger.warning(f"Provider '{ptype}' raised: {str(e)[:160]} — next provider")
                text = ""
            if text:
                logger.info(f"Script generated via provider: {ptype} "
                            f"({provider.get('model') or provider.get('models')})")
                break
            logger.warning(f"Provider '{ptype}' returned nothing — falling back")

    if not text:
        raise RuntimeError("All LLM providers failed (no script text returned).")

    # ── Robust JSON extraction ────────────────────────────────────────────────
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned).strip()

    import json_repair

    try:
        # json_repair robustly handles unescaped quotes, missing brackets, and trailing commas
        parsed = json_repair.loads(cleaned)
        # json_repair sometimes returns a string if it completely failed to parse an object
        if isinstance(parsed, str):
            parsed = None
    except Exception as e:
        logger.error(f"json_repair failed: {e}")
        parsed = None

    if not isinstance(parsed, dict):
        raise ValueError(f"Could not parse Gemini JSON response: {cleaned[:300]}")

    title = _safe_title(str(parsed.get("title", "Untitled_Project")))
    script_rewritten = str(parsed.get("script_rewritten", ""))
    viral_title = str(parsed.get("viral_title", title))
    short_description = str(parsed.get("short_description", ""))
    hashtags = parsed.get("hashtags", [])
    hook_text = str(parsed.get("hook_text", "")).strip()
    engagement_question = str(parsed.get("engagement_question", "")).strip()
    thumbnail_prompt = str(parsed.get("thumbnail_prompt", "")).strip()
    thumbnail_text = str(parsed.get("thumbnail_text", "")).strip()
    thumbnail_keyword = str(parsed.get("thumbnail_keyword", "")).strip()
    scenes_raw = parsed.get("scenes", [])

    if len(scenes_raw) < 16:
        logger.warning(f"Only {len(scenes_raw)} scenes generated (expected 16-20)")

    scenes = []
    for s in scenes_raw:
        scene_text = str(s.get("scene_text", ""))
        word_count = len(scene_text.split())
        if not (6 <= word_count <= 12):
            logger.warning(f"Scene {s.get('scene_no')} has {word_count} words (expected 6-12): '{scene_text}'")

        emphasis_raw = s.get("emphasis_words", [])
        if isinstance(emphasis_raw, str):
            emphasis_raw = [w for w in re.split(r"[,\s]+", emphasis_raw) if w]
        emphasis_words = [str(w).strip() for w in (emphasis_raw or []) if str(w).strip()]

        scenes.append(
            Scene(
                scene_no=_parse_scene_no(s.get("scene_no", 0)),
                scene_text=scene_text,
                image_prompt=str(s.get("image_prompt", "")),
                voice_text=str(s.get("voice_text", "")).strip(),
                motion=str(s.get("motion", "cinematic_push")),
                duration=_parse_duration(s.get("duration", 2.0)),
                scene_energy=str(s.get("scene_energy", "medium")),
                transition_to_next=str(s.get("transition_to_next", "")),
                voice_tone=str(s.get("voice_tone", "neutral")).strip().lower() or "neutral",
                sfx=str(s.get("sfx", "")).strip().lower(),
                emphasis_words=emphasis_words,
                graphic=_parse_graphic(s.get("graphic"), _parse_scene_no(s.get("scene_no", 0))),
            )
        )
    for extra in [s for s in scenes if s.graphic][MAX_GRAPHICS:]:
        extra.graphic = {}
    # Spoken length is driven by the sum of scene_text words (each scene's
    # duration = its TTS audio). Budget 130-170 words ≈ 50-65s at ~0.95 speed,
    # which keeps average-view-duration above the ~80% mark where Shorts
    # distribution opens up. Longer cuts retention, not comprehension.
    total_words = sum(len(s.scene_text.split()) for s in scenes)
    if 118 <= total_words <= 185:
        logger.info(f"Spoken word budget OK: {total_words} words / {len(scenes)} scenes")
    else:
        logger.warning(
            f"Spoken word budget OFF-TARGET: {total_words} words across "
            f"{len(scenes)} scenes (target 130-170) — video length may drift"
        )

    # ── Thumbnail defaults ────────────────────────────────────────────────────
    if not thumbnail_text:
        thumbnail_text = hook_text
    if not thumbnail_prompt and scenes:
        thumbnail_prompt = scenes[0].image_prompt
    if not thumbnail_keyword and thumbnail_text:
        # longest word in the headline (skip tiny filler words)
        words = [w.strip(".,!?:;\"'") for w in thumbnail_text.split()]
        words = [w for w in words if len(w) >= 3] or words
        thumbnail_keyword = max(words, key=len) if words else ""

    return ScriptResult(
        title=title,
        script_rewritten=script_rewritten,
        viral_title=viral_title,
        short_description=short_description,
        hashtags=hashtags,
        scenes=scenes,
        hook_text=hook_text,
        engagement_question=engagement_question,
        thumbnail_prompt=thumbnail_prompt,
        thumbnail_text=thumbnail_text,
        thumbnail_keyword=thumbnail_keyword,
    )
