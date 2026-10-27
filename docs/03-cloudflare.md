# 3 · Cloudflare — free AI images + R2 storage

Cloudflare gives you two free things this pipeline uses:

1. **Workers AI** — generates every scene image (FLUX.1 schnell model). **Required.**
2. **R2 storage** — gives Instagram a temporary public link to your video. **Recommended** (without it, a free public file host is used as fallback, which is less reliable).

---

## Part A — Create a Cloudflare account

1. Go to **https://dash.cloudflare.com/sign-up**, sign up with email + password and verify the email.
2. You do **not** need a domain. Skip any "add a site" prompt.
3. Note your **Account ID**: dashboard home → right sidebar (or *Workers & Pages → Overview*). You'll need it for R2.

---

## Part B — Deploy the image worker (no coding needed)

### Option 1: from the browser (easiest)

1. Dashboard → **Workers & Pages** → **Create** → **Create Worker** (choose "Start with Hello World").
2. Name it, e.g. `ai-image-worker` → **Deploy**.
3. Click **Edit code**. Delete everything in `worker.js`, then paste the full contents of [`cloudflare-worker/worker.js`](../cloudflare-worker/worker.js) from this repo → **Deploy**.
4. Go back to the worker → **Settings** → **Bindings** → **Add binding** → **Workers AI** → variable name **`AI`** → **Save/Deploy**.
   > Without this binding you'll get `Cannot read properties of undefined (reading 'run')`.
5. (Recommended) Protect your worker so strangers can't burn your quota:
   **Settings → Variables and Secrets → Add** → Type **Secret**, Name **`ACCESS_KEY`**, Value: any long random string (e.g. from https://www.uuidgenerator.net) → **Deploy**.
6. Copy the worker URL shown on its overview page, e.g.
   `https://ai-image-worker.your-name.workers.dev`

### Option 2: from the terminal (Wrangler)

```bash
npm install -g wrangler
cd cloudflare-worker
wrangler login
wrangler deploy
wrangler secret put ACCESS_KEY      # paste a long random string
```

### Test it

PowerShell:
```powershell
$body = '{"prompt":"ancient roman legion at sunset, cinematic","width":1024,"height":1792}'
Invoke-RestMethod -Method Post -Uri "https://ai-image-worker.your-name.workers.dev/?key=YOUR_ACCESS_KEY" -ContentType "application/json" -Body $body | Select-Object -ExpandProperty image_base64 | Measure-Object -Character
```
macOS / Linux:
```bash
curl -s -X POST "https://ai-image-worker.your-name.workers.dev/?key=YOUR_ACCESS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"ancient roman legion at sunset, cinematic"}' | head -c 200
```
You should see a long `image_base64` string. `401 unauthorized` = wrong key.

### Add it to `config.yaml`

```yaml
image_providers:
  - "https://ai-image-worker.your-name.workers.dev/?key=YOUR_ACCESS_KEY"
```

### How many images per day?

The Workers AI free plan includes **10,000 neurons per day** per account. When a worker's daily allowance runs out it returns error `4006`; the pipeline then skips that worker for the rest of the run and uses the next one in the list.

- One short uses one image per scene, so check how many videos per day your quota covers by running a test day.
- Need more? Either upgrade to **Workers Paid** ($5/month, much higher limits) or add more worker URLs to `image_providers` (for example, workers deployed by teammates on their own accounts). Respect Cloudflare's terms of service.

### Other models

Set a `MODEL` variable on the worker (Settings → Variables) to use another Workers AI text-to-image model, e.g. `@cf/bytedance/stable-diffusion-xl-lightning`. The worker handles both response formats.

---

## Part C — R2 bucket for Instagram uploads

Instagram's API does not accept a file upload — it downloads the video from a **public URL**. The pipeline puts the video in R2, gives Instagram a temporary signed link (valid 6 h), and automatically deletes old files, so storage stays near zero.

1. Dashboard → **R2 Object Storage** → **Get started / Purchase R2**.
   Cloudflare asks for a payment method to enable R2, but the free tier (10 GB storage, 1M writes/month, free egress) is far more than this pipeline uses — **you won't be charged**.
2. **Create bucket** → name `ig-videos` → location *Automatic* → **Create**.
3. R2 overview → **Manage R2 API Tokens** (or *API → Manage API tokens*) → **Create API token**:
   - Permissions: **Object Read & Write**
   - Specify bucket: **ig-videos** only
   - TTL: Forever → **Create**
4. Copy the values shown **once**:
   - **Access Key ID**
   - **Secret Access Key**
   - **S3 endpoint**: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`

These go into GitHub secrets (guide 6):

| Secret | Value |
|---|---|
| `IG_S3_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `IG_S3_BUCKET` | `ig-videos` |
| `IG_S3_ACCESS_KEY_ID` | Access Key ID |
| `IG_S3_SECRET_ACCESS_KEY` | Secret Access Key |
| `IG_S3_REGION` | `auto` |
| `IG_S3_PREFIX` | `instagram` (optional) |
| `IG_S3_PUBLIC_BASE_URL` | leave empty (signed URLs are used) |

To test locally, set the same names as environment variables before running.

➡️ Next: [4 · Social media APIs](04-social-apis.md)
