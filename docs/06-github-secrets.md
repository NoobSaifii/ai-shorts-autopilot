# 6 · GitHub repository & secrets

All your keys live in **GitHub Secrets** — encrypted, never visible in the repo or in logs, and **not** copied to forks.

## 6.1 Make your repository public

GitHub Actions minutes are **free and unlimited for public repositories** (private repos get 2,000 min/month, which a daily multi-channel run uses up quickly).

Public code is safe **because no secret is in the code**. Before your first push, double-check:

```bash
git status --ignored     # config.yaml, client_secrets.json, youtube_credentials_*.json … must be under "Ignored files"
```

Your repo → **Settings → General → Danger Zone → Change visibility → Public** (if it isn't already).

## 6.2 Enable Actions

Repo → **Actions** tab → *I understand my workflows, go ahead and enable them* (forks/templates have Actions disabled by default).

Repo → **Settings → Actions → General → Workflow permissions** → **Read and write permissions** → Save. (Needed to commit `topics.xlsx` statuses back.)

## 6.3 Create the secrets — automatic way (recommended)

Install the GitHub CLI (https://cli.github.com), then:

```bash
gh auth login
python scripts/make_secrets.py --upload YOUR_USERNAME/YOUR_REPO
```

This base64-encodes your local `config.yaml`, `gemini_keys.txt`, `google_service_account.json`, `client_secrets.json` and zips every `youtube_credentials_*.json` / `youtube_analytics_*.json` into one secret — and uploads them without printing anything.

## 6.4 Create the secrets — manual way

```bash
python scripts/make_secrets.py      # writes github_secrets.txt (gitignored)
```

Open `github_secrets.txt`; for each block go to **Settings → Secrets and variables → Actions → New repository secret**, paste the name and the value. **Delete `github_secrets.txt` afterwards.**

## 6.5 All secrets

| Secret | Required? | What |
|---|---|---|
| `CONFIG_YAML_B64` | ✅ | your whole `config.yaml` (from make_secrets.py) |
| `YT_CLIENT_SECRETS_B64` | ✅ for YouTube | `client_secrets.json` |
| `YT_TOKENS_B64` | ✅ for YouTube | zip of all `youtube_credentials_*.json` (+ analytics) |
| `GEMINI_KEYS_B64` | optional | `gemini_keys.txt` for key rotation |
| `GOOGLE_SA_B64` | optional | `google_service_account.json` (Google Sheets topics / TikTok tokens) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | optional | only if used via `api_key_env` |
| `IG_S3_ENDPOINT_URL`, `IG_S3_BUCKET`, `IG_S3_ACCESS_KEY_ID`, `IG_S3_SECRET_ACCESS_KEY`, `IG_S3_REGION` | recommended for Instagram | Cloudflare R2 ([guide 3](03-cloudflare.md#part-c--r2-bucket-for-instagram-uploads)) |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `GMAIL_TO` | optional | email report after each channel (see below) |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | optional | TikTok |

> **Whenever you change `config.yaml` or re-login a YouTube channel, run `make_secrets.py` again** — the cloud only sees what's in the secrets.

## 6.6 Email notifications (optional)

1. Turn on 2-Step Verification for the Gmail account: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords → name it `pipeline` → copy the 16-character password.
3. Secrets: `GMAIL_ADDRESS` = that Gmail, `GMAIL_APP_PASSWORD` = the app password, `GMAIL_TO` = where to receive reports.

## 6.7 First cloud run

Repo → **Actions → Auto Daily Video Upload → Run workflow**:
- *channel*: `Blade Archives` (one channel to test)
- *no_upload*: ✅ (first run: only render, no posting)

Watch the logs. A full channel takes ~15–30 minutes. When it's green, run again with *no_upload* unticked to test real uploads.

## 🔒 Security checklist

- [ ] `config.yaml` and all credential JSONs are **ignored** by git
- [ ] No key appears in any committed file (`git grep -n "AIza\|EAA"` returns nothing)
- [ ] Image worker protected with `ACCESS_KEY`
- [ ] R2 token limited to one bucket
- [ ] `github_secrets.txt` deleted
- [ ] If anything ever leaks: **revoke the key first**, then remove it from history

➡️ Next: [7 · Run 24/7 for free](07-automation-24x7.md)
