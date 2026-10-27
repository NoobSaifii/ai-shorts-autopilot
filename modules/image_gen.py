import base64
import logging
from typing import List, Optional

import httpx
from PIL import Image
import io

logger = logging.getLogger("pipeline.image_gen")

MIN_IMAGE_BYTES = 5_000
MIN_DIMENSION_PX = 512

# Keywords that mean this worker's DAILY quota is used up.
# When seen, the worker is blacklisted for the ENTIRE Python process run
# (across all channels, all scenes) — no point retrying until tomorrow.
_DAILY_LIMIT_SIGNALS = ("4006", "daily free allocation", "10,000 neurons")

# Keywords that mean Cloudflare blocked the prompt (content policy, error 3030).
_CONTENT_BLOCK_SIGNALS = (
    "3030", "nsfw", "content policy", "inappropriate",
    "safety", "blocked", "filtered", "adult", "explicit",
)


class AllProvidersExhausted(Exception):
    """Raised when every available provider returned an error for a given prompt."""
    def __init__(self, message: str, likely_content_block: bool = False):
        super().__init__(message)
        self.likely_content_block = likely_content_block


class ImageGenerator:
    # ── Class-level blacklist ─────────────────────────────────────────────────
    # Shared across ALL ImageGenerator instances in this Python process.
    # A worker goes here the moment it returns a 4006 daily-limit error.
    # It stays here for the rest of the run (never retried, even for new channels).
    _run_daily_exhausted: set = set()

    @classmethod
    def _blacklist_worker(cls, url: str) -> None:
        """Permanently skip this worker for the rest of today's pipeline run."""
        if url not in cls._run_daily_exhausted:
            cls._run_daily_exhausted.add(url)
            logger.warning(
                f"Worker daily quota exhausted — blacklisted for this run: "
                f"{url[:60]}... "
                f"({len(cls._run_daily_exhausted)} total blacklisted so far)"
            )

    def __init__(self, providers: List[str]):
        if not providers:
            raise ValueError("providers list cannot be empty")
        self.providers = list(providers)
        self._cursor = 0
        self._attempted: set = set()

    def reset_attempted(self):
        """Reset per-scene attempted set. Does NOT clear the run-level blacklist."""
        self._attempted = set()

    def _active_providers(self) -> List[str]:
        """Providers that are NOT in the run-level daily-exhausted blacklist."""
        return [p for p in self.providers if p not in ImageGenerator._run_daily_exhausted]

    def _next_provider(self) -> Optional[str]:
        active = self._active_providers()
        available = [p for p in active if p not in self._attempted]
        if not available:
            return None
        start = self._cursor % max(len(active), 1)
        for i in range(len(active)):
            idx = (start + i) % len(active)
            url = active[idx]
            if url not in self._attempted:
                self._cursor = idx
                return url
        return None

    def _validate_image(self, data: bytes) -> bool:
        if len(data) < MIN_IMAGE_BYTES:
            return False
        try:
            img = Image.open(io.BytesIO(data))
            w, h = img.size
            return w >= MIN_DIMENSION_PX and h >= MIN_DIMENSION_PX
        except Exception:
            return False

    async def generate_image(
        self,
        title: str,
        scene_no: int,
        prompt: str,
        width: int = 1024,
        height: int = 1792,
    ) -> bytes:
        self.reset_attempted()
        logger.debug(f"Scene {scene_no} prompt: {prompt[:300]}")

        active_count = len(self._active_providers())
        blacklisted = len(ImageGenerator._run_daily_exhausted)
        if blacklisted:
            logger.debug(
                f"Scene {scene_no}: {active_count} active workers "
                f"({blacklisted} blacklisted today)"
            )

        content_block_count = 0  # providers that signalled a content policy block

        while True:
            provider_url = self._next_provider()
            if provider_url is None:
                total_active = len(self._active_providers())
                likely_block = content_block_count > (total_active * 0.4)
                logger.error(
                    f"Scene {scene_no}: ALL {active_count} active providers exhausted "
                    f"({'content policy' if likely_block else 'rate limit / server error'}).\n"
                    f"  FAILED PROMPT: {prompt}"
                )
                raise AllProvidersExhausted(
                    f"All {active_count} active providers exhausted for scene {scene_no}",
                    likely_content_block=likely_block,
                )

            self._attempted.add(provider_url)

            try:
                image_bytes = await self._request(provider_url, title, scene_no, prompt, width, height)
                if self._validate_image(image_bytes):
                    logger.info(
                        f"Scene {scene_no}: image OK from {provider_url[:50]}... "
                        f"({len(image_bytes)//1024}KB)"
                    )
                    return image_bytes
                else:
                    logger.warning(
                        f"Scene {scene_no}: image from {provider_url[:50]}... "
                        f"failed validation — trying next"
                    )
            except Exception as e:
                err_str = str(e).lower()

                if any(sig in err_str for sig in _DAILY_LIMIT_SIGNALS):
                    # Worker's daily neuron quota is used up — blacklist for entire run
                    ImageGenerator._blacklist_worker(provider_url)
                elif any(sig in err_str for sig in _CONTENT_BLOCK_SIGNALS):
                    content_block_count += 1

                logger.warning(
                    f"Scene {scene_no}: provider {provider_url[:50]}... "
                    f"error: {e} — trying next"
                )

    async def _request(
        self,
        url: str,
        title: str,
        scene_no: int,
        prompt: str,
        width: int,
        height: int,
    ) -> bytes:
        body = {
            "title": title,
            "scene_no": scene_no,
            "prompt": prompt,
            "width": width,
            "height": height,
        }
        headers = {"Content-Type": "application/json"}

        # A healthy worker returns an image in ~5-6s; real generations almost
        # never exceed ~30s. The old 300s cap meant a single hung/exhausted
        # worker could stall a scene for 5 minutes. Tight timeouts fail over to
        # the next worker fast (10s to connect, 60s for the image itself).
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)

        if resp.status_code != 200:
            try:
                body_text = resp.text[:300]
            except Exception:
                body_text = "(unreadable)"
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code} | {body_text}",
                request=resp.request,
                response=resp,
            )

        data = resp.json()
        body_data = data if isinstance(data, dict) else {}

        image_b64: str = (
            body_data.get("image_base64")
            or body_data.get("data", {}).get("image_base64", "")
            or body_data.get("result", {}).get("image_base64", "")
            or ""
        )

        if not image_b64 or len(image_b64) < 20:
            raise ValueError(f"No valid image_base64 in response: {str(body_data)[:200]}")

        if "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1]

        return base64.b64decode(image_b64)
