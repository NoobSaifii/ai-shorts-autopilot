# 5 · Topics — what each video is about

Every channel reads its next topic from a **sheet/tab** whose name matches the channel's `sheet:` value in `config.yaml`. Each run takes the first row with status `pending`, makes the video, then marks it `Done`.

## Sheet format

Row 1 must be these headers (lower/upper case doesn't matter):

| # | topic | series_name | episode_no | priority | status |
|---|---|---|---|---|---|
| 1 | The Roman onager — a one-man siege catapult that… | Ancient Weapons | 1 | High | pending |
| 2 | Greek fire — the Byzantine liquid weapon nobody can recreate | Ancient Weapons | 2 | Medium | pending |

- **topic** — the more specific, the better the script. One concrete fact/story per row.
- **status** — `pending` = to do, `Done` = finished (set automatically).
- Rows are processed in `#` order.

> **Tip:** write topics in bulk with Gemini/ChatGPT ("give me 100 specific, verifiable facts about …"), then **verify them** — the script writer trusts your topic. Never repeat a topic.

## Option A — `topics.xlsx` (simplest)

A sample `topics.xlsx` with 3 example sheets is included. Open it in Excel / LibreOffice / Google Sheets (then download as .xlsx), add a sheet per channel, and commit it.

In the cloud, the workflow commits the updated file back to your repo after each run so `Done` statuses persist.

## Option B — Google Sheets (recommended for 24/7)

Statuses update live, you can add topics from your phone, and no git commits are needed.

1. Create a Google Sheet, one tab per channel (same headers as above). Tip: *File → Import* the sample `topics.xlsx`.
2. Copy the **sheet ID** from its URL: `https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`
3. Google Cloud Console (same project as YouTube) → **APIs & Services → Library** → enable **Google Sheets API**.
4. **IAM & Admin → Service Accounts → Create service account** → name `sheets-bot` → *Create and continue* → skip roles → **Done**.
5. Open the service account → **Keys → Add key → Create new key → JSON**. Rename the downloaded file to **`google_service_account.json`** and put it in the project root (gitignored).
6. Copy the service account's email (`sheets-bot@….iam.gserviceaccount.com`) → in your Google Sheet click **Share** → paste it → **Editor** → uncheck "Notify" → **Share**.
7. In `config.yaml`:
   ```yaml
   google_sheet_id: "1AbC...xyz"
   google_sa_file: google_service_account.json
   ```

If the service account file is missing or broken, the pipeline automatically falls back to `topics.xlsx`.

➡️ Next: [6 · GitHub secrets](06-github-secrets.md)
