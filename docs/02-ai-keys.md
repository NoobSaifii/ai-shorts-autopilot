# 2 · AI keys (script writer)

The script for every video is written by an LLM. **Gemini is free and is all you need.** Claude / OpenAI are optional upgrades.

## Google Gemini (free) — required

1. Go to **https://aistudio.google.com/apikey** and sign in with your Google account.
2. Click **Create API key** → **Create API key in new project**.
3. Copy the key (starts with `AIza…`).
4. In `config.yaml`:
   ```yaml
   gemini:
     api_key: "AIza...your key..."
   ```

### More free capacity: key rotation (optional)

The free tier has per-minute and per-day limits. You can create keys in a few different Google Cloud projects and list them **one per line** in a file named `gemini_keys.txt` in the project root:

```text
AIzaSy...key1
AIzaSy...key2
```

The pipeline rotates to the next key whenever one is rate-limited. The file is gitignored; in the cloud it comes from the `GEMINI_KEYS_B64` secret.

## Claude (optional, paid)

1. Create a key at **https://console.anthropic.com/settings/keys**.
2. Do **not** paste it into `config.yaml`. Instead, in `config.yaml` uncomment the `anthropic` provider:
   ```yaml
   llm:
     providers:
       - type: anthropic
         base_url: https://api.anthropic.com
         api_key_env: ANTHROPIC_API_KEY
         model: claude-sonnet-4-5
         max_tokens: 16000
         attempts: 3
       - type: gemini
         models: [gemini-2.5-flash]
   ```
3. Locally: set the environment variable `ANTHROPIC_API_KEY`. In the cloud: add a GitHub secret named `ANTHROPIC_API_KEY` (guide 6).

Providers are tried top to bottom — if Claude fails, Gemini takes over automatically.

## OpenAI-compatible (optional)

Works with OpenAI, OpenRouter, Groq, Together, DeepSeek, local LM Studio, etc.:

```yaml
      - type: openai
        base_url: https://api.openai.com      # or https://openrouter.ai/api
        api_key_env: OPENAI_API_KEY
        model: gpt-4o-mini
```

Add the `OPENAI_API_KEY` GitHub secret.

## Customising the writing style

Each channel uses `prompts/<Channel Name>.txt`. The file name must match the channel `name` in `config.yaml` exactly (if no file exists, `prompts/Restricted Lore.txt` is used). Copy an existing prompt (e.g. `prompts/Blade Archives.txt`) and adapt the niche, tone and audience.

Rules for prompt files:
- Keep the placeholders `{series_name}`, `{episode_no}` and `{topic}` — they are filled from your topics sheet.
- Any literal `{` or `}` (e.g. in the JSON example) must be **doubled**: `{{` and `}}`.
- Keep the JSON output format of the original prompt — the pipeline parses it.

➡️ Next: [3 · Cloudflare](03-cloudflare.md)
