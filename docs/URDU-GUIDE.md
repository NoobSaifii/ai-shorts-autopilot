# 🇵🇰 Mukammal Setup Guide (Roman Urdu / Hindi)

Ye guide un dosto ke liye hai jo English docs se ghabraate hain. Har step asaan alfaaz mein — tafseeli screenshots-level detail English guides (`docs/01` se `docs/08`) mein hai, yahan unka khulasa aur sahi tarteeb hai.

> **Ek baat yaad rakhein:** apni koi bhi key / token / password kabhi code, issue, ya kisi ko message mein na bhejein. Sab kuch sirf `config.yaml` (jo GitHub par nahi jaata) aur GitHub Secrets mein rakhna hai.

---

## Ye project karta kya hai?

Aap Excel / Google Sheet mein topics likhte hain → har roz system khud:
1. Gemini AI se script likhta hai
2. Kokoro AI se awaaz (voiceover) banata hai
3. Cloudflare AI se har scene ki tasveer banata hai
4. FFmpeg se cinematic video, captions, music ke saath edit karta hai
5. YouTube Shorts, Instagram Reels aur Facebook Reels par upload kar deta hai
6. Topic ko `Done` mark kar deta hai

Ye sab **GitHub ke free server** par chalta hai — aap ka PC band ho tab bhi. **Kharcha: 0 rupay.**

---

## Step 1 — Accounts banayein (sab free)
- **GitHub** — github.com
- **Google account** (Gmail) — Gemini key aur YouTube API ke liye
- **Cloudflare** — dash.cloudflare.com (tasveerein free banane ke liye)
- **Meta Developers** — developers.facebook.com (Insta/FB upload ke liye)
- **cron-job.org** — roz time par video chalane ke liye

Aur: ek YouTube channel, ek Facebook Page, aur us Page se linked Instagram **Professional** account.

## Step 2 — PC par software install karein
- **Python 3.11** (install karte waqt "Add to PATH" ✅ zaroor karein)
- **Git**
- **FFmpeg** — PowerShell mein: `winget install --id Gyan.FFmpeg -e`
- (optional) Node.js 22, eSpeak NG

Phir is repo ko apne account mein copy karein: upar **Use this template → Create a new repository** → **Public** rakhein.
Apne PC par:
```bash
git clone https://github.com/APKA_USERNAME/APKA_REPO.git
cd APKA_REPO
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python -m spacy download en_core_web_sm
copy config.example.yaml config.yaml
```
Kokoro voice model ki 2 files `kokoro_models` folder mein daalein (links `docs/01-prerequisites.md` mein hain).

## Step 3 — Gemini key (free) 
1. https://aistudio.google.com/apikey → **Create API key**
2. `config.yaml` mein `gemini: api_key:` ke aage paste karein.
3. Zyada videos ke liye kai keys `gemini_keys.txt` mein ek line par ek key likh dein — system khud rotate karega.

## Step 4 — Cloudflare (tasveerein + Instagram storage)
**Image worker:**
1. Cloudflare dashboard → **Workers & Pages → Create → Create Worker** → Deploy
2. **Edit code** → is repo ki `cloudflare-worker/worker.js` ka poora code paste → Deploy
3. Worker → **Settings → Bindings → Add → Workers AI** → naam **`AI`**
4. **Settings → Variables and Secrets** → Secret `ACCESS_KEY` = koi lamba random password
5. Worker ka URL `config.yaml` mein `image_providers:` ke neeche likhein:
   `https://ai-image-worker.apka-naam.workers.dev/?key=APKA_ACCESS_KEY`

Free plan mein roz 10,000 "neurons" milte hain. Khatam ho jaayein to system agla worker use karta hai.

**R2 (Instagram ke liye):** R2 → bucket `ig-videos` banayein → **Manage API tokens** → Object Read & Write token → Access Key ID, Secret Key, aur endpoint note karein (ye GitHub secrets mein jayenge). Card maangta hai magar free limit mein **koi charge nahi**.

## Step 5 — YouTube API
1. https://console.cloud.google.com → New Project
2. **Library** → **YouTube Data API v3** → Enable
3. **OAuth consent screen** → External → apna email → **Test users** mein apna channel wala Gmail add karein
4. **Publish app** zaroor karein (warna 7 din baad upload band ho jayega)
5. **Credentials → OAuth client ID → Desktop app** → JSON download → naam `client_secrets.json` rakh kar project folder mein daalein
6. `python auth_yt.py` chalayein → browser khulega → sahi channel select karein

Note: ek Google project se roz ~6 uploads hote hain. Zyada channels hain to doosra project bana lein.

## Step 6 — Instagram + Facebook API
1. developers.facebook.com → **Create App** → Business
2. **Graph API Explorer** kholein → apni app select → permissions add karein:
   `pages_show_list, pages_read_engagement, pages_manage_posts, instagram_basic, instagram_content_publish, business_management`
3. **Generate Access Token** → apna Page aur Insta select karein
4. Is chhote token ko lambe token mein badlein, phir `me/accounts` se **Page token** nikalein (ye kabhi expire nahi hota) — exact links `docs/04-social-apis.md` (B4) mein hain
5. `PAGE_ID?fields=instagram_business_account` se Instagram ID nikalein
6. Teeno cheezein `config.yaml` mein channel ke `upload:` hissay mein daalein

## Step 7 — Topics
`topics.xlsx` khol kar har channel ki sheet mein topics likhein, status `pending` rakhein. Sheet ka naam wahi ho jo `config.yaml` mein `sheet:` hai.
Behtar tareeqa: Google Sheet + service account (`docs/05-topics.md`).

## Step 8 — Pehla test (PC par)
```bash
python daily_runner.py --channel "Blade Archives" --no-upload --keep-output
```
Video `output/` folder mein ban jayegi. Dekh lein sab theek hai.

## Step 9 — GitHub Secrets (sab keys cloud mein)
```bash
gh auth login
python scripts/make_secrets.py --upload APKA_USERNAME/APKA_REPO
```
Ye script khud sab files encode kar ke GitHub Secrets mein daal deti hai. R2 aur Gmail wale secrets haath se add karein: Repo → **Settings → Secrets and variables → Actions → New repository secret** (list `docs/06-github-secrets.md` mein).

Repo → **Settings → Actions → General → Workflow permissions → Read and write** ✅
Repo → **Actions** tab → workflows enable karein.

Test: **Actions → Auto Daily Video Upload → Run workflow** → channel likhein, `no_upload` ✅ → Run.

## Step 10 — 24/7 free automation (cron-job.org) ⏰
Ye sab se zaroori step hai — isi se roz khud video banti aur upload hoti hai.

**A. GitHub token banayein:**
github.com/settings/personal-access-tokens/new → *Only select repositories* → apni repo → **Permissions → Actions: Read and write** → Generate → token copy karein.

**B. cron-job.org par job:**
- **URL:** `https://api.github.com/repos/APKA_USERNAME/APKA_REPO/actions/workflows/auto_daily_upload.yml/dispatches`
- **Schedule:** roz, jo time aap chahein (time zone `Asia/Karachi` select karein)
- **Advanced → Method:** `POST`
- **Headers:**
  - `Accept` = `application/vnd.github+json`
  - `Authorization` = `Bearer APKA_TOKEN`
  - `X-GitHub-Api-Version` = `2022-11-28`
  - `Content-Type` = `application/json`
- **Body:** `{"ref":"main"}`
- **Test run** → jawab `204` aaye to kaam ho gaya ✅

Ab har roz us time par GitHub ka free server khud chalega, video banayega aur upload karega. Ek din mein 2 baar chahiye to doosri cron job bana lein.

**Kyun free hai?** Public repo par GitHub Actions ke minutes unlimited free hain, aur cron-job.org bhi free hai. Aap ki keys public nahi hotin — wo encrypted secrets mein hain aur logs mein `***` dikhti hain.

---

## Masla aa jaye to?
`docs/08-troubleshooting.md` dekhein — aam errors aur unka hal wahan hai. Phir bhi na bane to GitHub par issue kholein (**key/token kabhi paste na karein**).

Agar project pasand aaye to ⭐ dein aur [@BladeArchives1](https://www.youtube.com/@BladeArchives1) subscribe karein!
