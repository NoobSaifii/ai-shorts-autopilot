import asyncio
import logging
import os
import subprocess

logger = logging.getLogger("pipeline.tts")

# kokoro_voice -> (kokoro_voice, edge_tts_fallback_voice)
# Kokoro v1.0 voices. Edge fallback chosen to match gender/accent so a cloud
# fallback never flips a channel's voice identity.
VOICE_MAP = {
    # ── Per-channel production voices (v1.0) ──────────────────────────────
    "bm_george":             ("bm_george",  "en-GB-RyanNeural"),         # Restricted Lore
    "af_bella":              ("af_bella",   "en-US-JennyNeural"),        # Classified Cognition
    "am_michael":            ("am_michael", "en-US-GuyNeural"),          # Filed And Forgotten
    "bm_fable":              ("bm_fable",   "en-GB-ThomasNeural"),       # Ruined Clock
    "am_fenrir":             ("am_fenrir",  "en-US-ChristopherNeural"),  # Fracture Layer
    "af_nicole":             ("af_nicole",  "en-US-AriaNeural"),         # The Cursed Map
    "am_onyx":               ("am_onyx",    "en-US-ChristopherNeural"),  # Blade Archives
    "bf_emma":               ("bf_emma",    "en-GB-SoniaNeural"),        # Covered Pages
    "bm_lewis":              ("bm_lewis",   "en-GB-RyanNeural"),         # Erased Lore
    "af_heart":              ("af_heart",   "en-US-AriaNeural"),         # Myth Bleed
    # ── Hindi/Urdu native voices — edge-tts only (bypass Kokoro) ──────────
    "hi-IN-SwaraNeural":     (None,         "hi-IN-SwaraNeural"),        # Muslim Ummah Awareness Hub (Hindi Female)
    "hi-IN-MadhurNeural":    (None,         "hi-IN-MadhurNeural"),       # Hindi Male fallback
    "ur-PK-UzmaNeural":      (None,         "ur-PK-UzmaNeural"),         # Urdu Female Pakistan
    "ur-PK-AsadNeural":      (None,         "ur-PK-AsadNeural"),         # Urdu Male Pakistan
    # ── Legacy keys (old configs / stale CONFIG_YAML_B64 secret) ─────────
    "am_adam":               ("am_michael", "en-US-GuyNeural"),          # am_adam is F-grade in v1.0
    "en-US-GuyNeural":       ("am_michael", "en-US-GuyNeural"),
    "en-GB-RyanNeural":      ("bm_george",  "en-GB-RyanNeural"),
}

# Voices that must skip Kokoro entirely and go direct to edge-tts.
# These are native-language voices (Hindi, Urdu) that Kokoro cannot handle.
EDGE_ONLY_VOICES: set[str] = {
    "hi-IN-SwaraNeural", "hi-IN-MadhurNeural",
    "ur-PK-UzmaNeural",  "ur-PK-AsadNeural",
    "ur-IN-GulNeural",   "ur-IN-SalmanNeural",
}

DEFAULT_VOICE_PAIR = ("am_michael", "en-US-GuyNeural")

# Deep male voices get a slight pitch drop on the edge-tts fallback only.
# Never pitch-shift female voices — it sounds wrong.
_EDGE_PITCH_DROP_VOICES = {"am_onyx", "bm_lewis"}

# Try to load kokoro-onnx (high quality, no PyTorch needed)
try:
    from kokoro_onnx import Kokoro as KokoroOnnx
    import soundfile as sf
    import numpy as np
    _KOKORO_AVAILABLE = True
    logger.info("kokoro-onnx loaded — high quality TTS active")
except Exception:
    _KOKORO_AVAILABLE = False
    logger.info("kokoro-onnx not available — falling back to edge-tts")

# Try to load misaki — Kokoro's own G2P. It carries a 179k-word gold lexicon
# plus POS tagging, so homographs ("read", "lead", "bow") and most proper nouns
# resolve correctly instead of going through espeak's letter rules. espeak stays
# on as the per-word fallback for anything the lexicon misses.
try:
    from misaki import en as _misaki_en, espeak as _misaki_espeak
    _MISAKI_AVAILABLE = True
    logger.info("misaki G2P loaded — lexicon-based pronunciation active")
except Exception:
    _MISAKI_AVAILABLE = False
    logger.info("misaki not available — falling back to espeak G2P")

# One G2P per accent (american/british); building one is expensive so cache it.
_G2P_CACHE: dict = {}
_LEXICON: dict | None = None
# Per-job overrides injected at runtime (e.g. a pronunciation map returned with
# the script). Cleared between jobs via reset_pronunciations().
_RUNTIME_LEXICON: dict = {}


def _load_lexicon() -> dict:
    """Load pronunciations.yaml once — word -> Kokoro phoneme string."""
    global _LEXICON
    if _LEXICON is None:
        _LEXICON = {}
        try:
            import yaml
            from pathlib import Path
            path = Path(__file__).resolve().parent.parent / "pronunciations.yaml"
            if path.exists():
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                for word, phonemes in (data.get("words") or {}).items():
                    _LEXICON[str(word).lower()] = str(phonemes)
                logger.info(f"pronunciations.yaml: {len(_LEXICON)} custom entries")
        except Exception as e:
            logger.warning(f"pronunciations.yaml load failed (non-fatal): {e}")
    return _LEXICON


def add_pronunciations(mapping: dict):
    """Inject per-job pronunciations (word -> phonemes). Applied to live G2Ps."""
    for word, phonemes in (mapping or {}).items():
        key = str(word).lower().strip()
        if not key or not phonemes:
            continue
        _RUNTIME_LEXICON[key] = str(phonemes)
        for g2p in _G2P_CACHE.values():
            g2p.lexicon.golds[key] = str(phonemes)


def reset_pronunciations():
    """Drop per-job overrides so one video's names never leak into the next."""
    _RUNTIME_LEXICON.clear()
    _G2P_CACHE.clear()


def _get_g2p(british: bool):
    """Build (and cache) a misaki G2P for the given accent, lexicon applied."""
    if british not in _G2P_CACHE:
        fallback = _misaki_espeak.EspeakFallback(british=british)
        g2p = _misaki_en.G2P(trf=False, british=british, fallback=fallback)
        for word, phonemes in {**_load_lexicon(), **_RUNTIME_LEXICON}.items():
            g2p.lexicon.golds[word] = phonemes
        _G2P_CACHE[british] = g2p
    return _G2P_CACHE[british]


def _fix_hindi_pronunciation(text: str) -> str:
    """Fix common mispronunciations for hi-IN TTS reading Islamic/Urdu words."""
    fixes = {
        "फ़िरऔन": "फ़िरौन",
        "फिरऔन": "फ़िरौन",
        "बनी इसराइल": "बनी इसराईल",
        "अलैहिस्सलाम": "अलै-हिस-सलाम",
        "मुक़ाबला": "मुकाबला",
        "क़ौम": "कौम",
        "ज़ुल्म": "ज़ुल्म",
        "ग़ुलाम": "गुलाम",
        "पैग़ंबर": "पैगंबर",
        "वाक़िया": "वाक़िया",
        "हज़रत": "हज़रत",
        "क़ुरान": "क़ुरान",
        "कुदरत": "क़ुदरत",
        "मंज़र": "मंज़र",
        "आज़ाद": "आज़ाद",
        "क़": "क", "ख़": "ख", "ग़": "ग", "ज़": "ज़", "फ़": "फ़"
    }
    for old, new in fixes.items():
        text = text.replace(old, new)
    return text

def _speed_to_rate(speed: float) -> str:
    pct = int(round((speed - 1.0) * 100))
    return f"{pct:+d}%"


async def ensure_kokoro_running(*args, **kwargs):
    pass


class KokoroClient:
    _kokoro_instance = None

    def __init__(self, base_url: str = ""):
        pass

    def _get_kokoro(self):
        if self._kokoro_instance is None and _KOKORO_AVAILABLE:
            from pathlib import Path
            # Look for model files in kokoro_models/ next to repo root
            base = Path(__file__).resolve().parent.parent / "kokoro_models"
            model_path  = base / "kokoro-v1.0.onnx"
            voices_path = base / "voices-v1.0.bin"
            if not model_path.exists() or not voices_path.exists():
                # Stale cache / not yet downloaded — fall back to v0.19 files
                legacy_model  = base / "kokoro-v0_19.onnx"
                legacy_voices = base / "voices.bin"
                if legacy_model.exists() and legacy_voices.exists():
                    logger.warning(
                        "Kokoro v1.0 model files not found — using legacy v0.19 "
                        "(voice quality reduced). Download kokoro-v1.0.onnx + "
                        "voices-v1.0.bin into kokoro_models/ to upgrade."
                    )
                    model_path, voices_path = legacy_model, legacy_voices
                else:
                    raise FileNotFoundError(
                        f"Kokoro model files not found at {base}. "
                        "Run the download step or check kokoro_models/ folder."
                    )
            KokoroClient._kokoro_instance = KokoroOnnx(str(model_path), str(voices_path))
        return KokoroClient._kokoro_instance

    async def generate_voiceover(
        self,
        text: str,
        voice: str,
        speed: float,
        output_path: str,
        voice_ref: str = "",
    ) -> float:
        kokoro_voice, edge_voice = VOICE_MAP.get(voice, DEFAULT_VOICE_PAIR)

        # Native Hindi/Urdu voices: skip Kokoro entirely — go straight to edge-tts.
        if voice in EDGE_ONLY_VOICES or kokoro_voice is None:
            import edge_tts as _etts
            rate = _speed_to_rate(speed)
            
            if "hi-IN" in edge_voice or "ur-PK" in edge_voice:
                text = _fix_hindi_pronunciation(text)
                
            logger.info(f"edge-tts (native lang): voice={edge_voice} rate={rate} chars={len(text)}")
            communicate = _etts.Communicate(text, edge_voice, rate=rate)
            await communicate.save(output_path)
            self._strip_trailing_silence(output_path)
            return await self.get_audio_duration(output_path)

        # British voices ("b" prefix) need British phonemes for the right accent
        kokoro_lang = "en-gb" if kokoro_voice.startswith("b") else "en-us"

        # ── Pocket TTS (per-channel unique voice), Kokoro is its fallback ────
        if voice_ref:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._pocket_generate, text, voice_ref, speed, output_path)
                logger.info(f"pocket-tts: voice={voice_ref} speed={speed} → {output_path}")
                self._strip_trailing_silence(output_path)
                return await self.get_audio_duration(output_path)
            except Exception as e:
                logger.warning(f"pocket-tts failed: {e} — falling back to Kokoro")

        # ── Try Kokoro ONNX first (high quality) ─────────────────────────────
        if _KOKORO_AVAILABLE:
            try:
                kokoro = self._get_kokoro()
                loop = asyncio.get_event_loop()

                # Prefer misaki phonemes; fall back to Kokoro's built-in espeak
                # path if the G2P errors on anything.
                phonemes = None
                if _MISAKI_AVAILABLE:
                    try:
                        g2p = _get_g2p(kokoro_lang == "en-gb")
                        phonemes = (await loop.run_in_executor(None, lambda: g2p(text)))[0]
                    except Exception as e:
                        logger.warning(f"misaki G2P failed: {e} — using espeak G2P")

                if phonemes:
                    samples, sample_rate = await loop.run_in_executor(
                        None,
                        lambda: kokoro.create(phonemes, voice=kokoro_voice, speed=speed, is_phonemes=True)
                    )
                else:
                    samples, sample_rate = await loop.run_in_executor(
                        None,
                        lambda: kokoro.create(text, voice=kokoro_voice, speed=speed, lang=kokoro_lang)
                    )
                import soundfile as sf
                sf.write(output_path, samples, sample_rate)
                g2p_tag = "misaki" if phonemes else "espeak"
                logger.info(f"kokoro-onnx[{g2p_tag}]: voice={kokoro_voice} speed={speed} → {output_path}")
                self._strip_trailing_silence(output_path)
                duration = await self.get_audio_duration(output_path)
                return duration
            except Exception as e:
                logger.warning(f"kokoro-onnx failed: {e} — falling back to edge-tts")

        # ── Fallback: edge-tts ─────────────────────────────────────────────
        import edge_tts
        rate = _speed_to_rate(speed)
        pitch = "-8Hz" if kokoro_voice in _EDGE_PITCH_DROP_VOICES else "+0Hz"
        logger.info(f"edge-tts: voice={edge_voice} rate={rate} pitch={pitch} chars={len(text)}")
        communicate = edge_tts.Communicate(text, edge_voice, rate=rate, pitch=pitch)
        await communicate.save(output_path)
        self._strip_trailing_silence(output_path)

        duration = await self.get_audio_duration(output_path)
        logger.info(f"TTS saved → {output_path} ({duration:.2f}s)")
        return duration

    _pocket_model = None
    _pocket_states: dict = {}

    def _pocket_generate(self, text: str, voice_ref: str, speed: float, output_path: str):
        """voice_ref: a Pocket built-in voice name, or (with the gated cloning
        weights + HF_TOKEN) a wav path / hf:// URL to clone. Pocket has no speed
        knob, so the channel speed is applied afterwards with atempo."""
        from pocket_tts import TTSModel
        import soundfile as sf
        if KokoroClient._pocket_model is None:
            KokoroClient._pocket_model = TTSModel.load_model()
        model = KokoroClient._pocket_model
        if voice_ref not in KokoroClient._pocket_states:
            KokoroClient._pocket_states[voice_ref] = model.get_state_for_audio_prompt(voice_ref)
        audio = model.generate_audio(KokoroClient._pocket_states[voice_ref], text)
        sf.write(output_path, audio.numpy(), model.sample_rate)
        if abs(speed - 1.0) > 0.01:
            tmp = output_path + ".tempo.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", output_path,
                            "-af", f"atempo={speed:.3f}", tmp], check=True)
            os.replace(tmp, output_path)

    async def get_audio_duration(self, audio_path: str) -> float:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._ffprobe_duration, audio_path)

    @staticmethod
    def _strip_trailing_silence(audio_path: str):
        """Lightly trim long trailing silence without clipping final syllables."""
        try:
            tmp = audio_path + ".stripped.wav"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", audio_path,
                    "-af", (
                        "silenceremove=stop_periods=-1:"
                        "stop_duration=0.35:stop_threshold=-40dB,"
                        "apad=pad_dur=0.15"
                    ),
                    "-ar", "24000", "-ac", "1",
                    tmp,
                ],
                capture_output=True, timeout=30,
            )
            if result.returncode == 0:
                import os
                os.replace(tmp, audio_path)
        except Exception as e:
            logger.warning(f"silence strip failed (non-fatal): {e}")

    @staticmethod
    def _ffprobe_duration(audio_path: str) -> float:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error",
                 "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1",
                 audio_path],
                capture_output=True, text=True, timeout=30,
            )
            raw = result.stdout.strip()
            val = float(raw) if raw else 0.0
            return max(val, 0.5)
        except Exception as e:
            logger.warning(f"ffprobe failed: {e} — defaulting 2.0s")
            return 2.0
