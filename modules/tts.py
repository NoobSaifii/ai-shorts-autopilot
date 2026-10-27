# tts.py — delegates to edge-tts implementation (no local Kokoro server needed)
from modules.tts_edge import KokoroClient, ensure_kokoro_running, VOICE_MAP  # noqa: F401
