# 7 · Run 24/7 for free (GitHub Actions + cron-job.org)

This is exactly how the [@BladeArchives1](https://www.youtube.com/@BladeArchives1) channel runs: **no server, no PC switched on, $0 per month.**

```text
cron-job.org  ──(at your chosen time)──►  GitHub API "workflow_dispatch"
                                              │
                                              ▼
                           GitHub Actions free Ubuntu runner (up to 6 h)
                           renders every channel → uploads → marks topics Done
```

## Why this setup?

| | |
|---|---|
| **GitHub Actions** | Public repositories get **unlimited free minutes** on standard runners. Each run gets a fresh Ubuntu machine (4 CPU cores, 16 GB RAM on public repos). |
| **cron-job.org** | Free, reliable scheduler. GitHub's own `schedule:` trigger is often delayed 10–60 minutes (or skipped) at busy times — an external trigger starts the job within seconds. |

## Step 1 — Create a GitHub token that can only start this workflow

1. GitHub → your avatar → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
   (direct link: https://github.com/settings/personal-access-tokens/new)
2. **Token name:** `cron-job-trigger`
3. **Expiration:** pick the longest you're comfortable with and set a reminder to renew it.
4. **Repository access:** *Only select repositories* → choose **your pipeline repo only**.
5. **Permissions → Repository permissions → Actions: Read and write.** Leave everything else *No access*.
6. **Generate token** → copy it (starts with `github_pat_…`). You won't see it again.

> This token can do one thing only: start/stop workflows in one repo. Even if cron-job.org leaked it, nobody could read your secrets or change your code.

## Step 2 — Create the cron job

1. Sign up / log in at **https://console.cron-job.org**.
2. **Cronjobs → Create cronjob**.
3. **Common** tab:
   - **Title:** `Daily shorts`
   - **URL:**
     ```text
     https://api.github.com/repos/YOUR_USERNAME/YOUR_REPO/actions/workflows/auto_daily_upload.yml/dispatches
     ```
   - **Execution schedule:** *Every day at* e.g. `18:00` — and set the **time zone** (top of the schedule box) to yours, e.g. `Asia/Karachi`.
4. **Advanced** tab:
   - **Request method:** `POST`
   - **Headers** — add these four:

     | Key | Value |
     |---|---|
     | `Accept` | `application/vnd.github+json` |
     | `Authorization` | `Bearer github_pat_YOUR_TOKEN` |
     | `X-GitHub-Api-Version` | `2022-11-28` |
     | `Content-Type` | `application/json` |

   - **Request body:**
     ```json
     {"ref":"main"}
     ```
     (Use your default branch name if it isn't `main`.)
   - **Treat redirects…** leave default. **Timeout:** 30 s is fine.
5. **Create**. Then click **Test run** → the response must be **`204 No Content`**.
6. Open your repo's **Actions** tab — a new *Auto Daily Video Upload* run has started. ✅

### Passing options from cron-job.org

The body can carry the same inputs as the *Run workflow* button:

```json
{"ref":"main","inputs":{"channel":"Blade Archives"}}
```
```json
{"ref":"main","inputs":{"skip_channels":"Myth Bleed,The Cursed Map"}}
```

### Several videos per day

Create more cron jobs (e.g. 09:00 and 18:00). Each run takes the **next pending topic** for every channel. Keep an eye on:
- **YouTube quota** — ~6 uploads/day per Google Cloud project ([guide 4](04-social-apis.md#a6-good-to-know)).
- **Image quota** — Cloudflare's 10,000 free neurons/day per account ([guide 3](03-cloudflare.md#how-many-images-per-day)).
- **6-hour job limit** — roughly 10–15 channels fit in one run. For more, split channels across cron jobs using `skip_channels` or `channel`.

The workflow has `concurrency` set, so two triggers never run at the same time — the second waits.

## Common responses from the test run

| Response | Meaning / fix |
|---|---|
| `204` | ✅ Workflow started |
| `401 Bad credentials` | Token wrong/expired, or missing `Bearer ` prefix |
| `403 Resource not accessible` | Token lacks **Actions: Read and write** or isn't scoped to this repo |
| `404 Not Found` | Wrong username/repo/file name, or Actions not enabled on the repo |
| `422 No ref found` | Branch in the body doesn't exist (`main` vs `master`) |

## Alternative without cron-job.org

Uncomment the `schedule:` block at the top of `.github/workflows/auto_daily_upload.yml`. Cron times there are **UTC** (Pakistan 18:00 PKT = `0 13 * * *`). Works, just less punctual.

## Keeping it healthy

- You get an email (if Gmail secrets are set) after each channel and on errors.
- GitHub also emails you when a workflow fails (Settings → Notifications → Actions).
- Refill topics before they run out — a channel with no `pending` rows is simply skipped.
- If you change `config.yaml` or re-login YouTube, re-run `python scripts/make_secrets.py --upload …`.

🎉 **That's it — your channels now post every day on their own.**

➡️ Problems? [8 · Troubleshooting](08-troubleshooting.md)
