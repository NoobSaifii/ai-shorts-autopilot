# 8 · Troubleshooting & FAQ

## Workflow / GitHub

| Symptom | Fix |
|---|---|
| `CONFIG_YAML_B64 secret is missing` | Run `python scripts/make_secrets.py --upload user/repo` (guide 6). |
| `Permission denied` / `403` when committing topics | Settings → Actions → General → Workflow permissions → **Read and write**. |
| Job cancelled at 6 h | Too many channels in one run. Split them across two cron jobs with `channel` / `skip_channels`. |
| `No space left on device` | Keep `pipeline.keep_intermediates` off (default in CI); fewer channels per run. |
| Old settings still used in the cloud | You edited `config.yaml` locally but didn't re-upload the secret. Re-run `make_secrets.py`. |

## Images

| Symptom | Fix |
|---|---|
| `All N active providers exhausted` + `4006` | Daily free Workers AI quota used up. Add more workers or upgrade (guide 3). |
| `401 unauthorized` from worker | `?key=` in `image_providers` doesn't match the worker's `ACCESS_KEY`. |
| `reading 'run'` error | Workers AI binding named `AI` missing on the worker. |
| Many `content policy` / `3030` errors | The prompt was blocked. Use less graphic topics or tone down the channel prompt's image style. |

## Script (LLM)

| Symptom | Fix |
|---|---|
| `429` / `RESOURCE_EXHAUSTED` | Gemini rate limit. Add more keys to `gemini_keys.txt`, or add a fallback provider. |
| `All LLM providers failed` | Check the key, model name, and that the Generative Language API is enabled in that project. |
| `KeyError` / `IndexError` while loading a prompt | A single `{` or `}` in your prompt file — double it: `{{` `}}`. |

## YouTube

| Symptom | Fix |
|---|---|
| `invalid_grant` / `Token has been expired or revoked` | OAuth app was in *Testing* (7-day tokens). Publish it (guide 4 · A3), run `python auth_yt.py` again, re-upload secrets. |
| `quotaExceeded` | 10,000 units/day/project ≈ 6 uploads. Use another project for extra channels or request more quota. |
| Upload works, thumbnail doesn't | Verify the channel by phone: https://www.youtube.com/verify |
| Video went to the wrong channel | During `auth_yt.py` you picked the wrong brand account. Delete that `youtube_credentials_*.json` and log in again. |

## Instagram / Facebook

| Symptom | Fix |
|---|---|
| `(#10) Application does not have permission` | Token is missing `instagram_content_publish` / `pages_manage_posts`. Regenerate it with all permissions (guide 4 · B3). |
| `Error validating access token: Session has expired` | You used the short-lived token. Use the never-expiring **Page** token (guide 4 · B4). |
| `Media upload has failed` / `2207026` | Instagram couldn't download the video. Set up R2 (guide 3 · C); the fallback hosts are sometimes slow. |
| Facebook reels get 0 views | New Pages with no followers get almost no Reels distribution. Grow the Page or remove `facebook` from `platforms`. |

## Local

| Symptom | Fix |
|---|---|
| `ffmpeg is not recognized` | Install FFmpeg and reopen the terminal (guide 1). |
| `kokoro-onnx not available — falling back to edge-tts` | Put `kokoro-v1.0.onnx` + `voices-v1.0.bin` in `kokoro_models/` and `pip install -r requirements.txt`. |
| Wrong pronunciation of a name | Add it to `pronunciations.yaml`. |

## FAQ

**Can I run it on my own PC instead of GitHub?**
Yes: `python daily_runner.py` (Windows Task Scheduler / cron to automate). The cloud is just free and always on.

**Can I make videos in Urdu / Hindi?**
Yes. Use an Edge voice such as `ur-PK-AsadNeural`, `ur-PK-UzmaNeural` or `hi-IN-SwaraNeural` as the channel `voice`, and write the channel prompt in that language.

**Does it make long (16:9) videos?**
The pipeline is tuned for vertical Shorts/Reels (≤ 175 s). A 16:9 thumbnail is generated but long-form isn't the default path yet — PRs welcome.

**Is it safe to make my repo public?**
Yes, as long as you follow the checklist in guide 6. Secrets are encrypted, masked in logs, never copied to forks, and the gitleaks scan blocks accidental commits of keys.

Still stuck? Open an [issue](../../../issues) — **never paste keys or tokens** into it.
