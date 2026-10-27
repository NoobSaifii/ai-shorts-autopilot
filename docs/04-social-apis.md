# 4 · YouTube, Instagram & Facebook APIs

Every platform uses its **official** API — no browser bots, no password sharing.

- [Part A — YouTube](#part-a--youtube-data-api-v3)
- [Part B — Instagram + Facebook (Meta Graph API)](#part-b--instagram--facebook-meta-graph-api)
- [Part C — TikTok (optional)](#part-c--tiktok-optional)

---

## Part A — YouTube Data API v3

You do this **once**. One Google Cloud project can serve many channels.

### A1. Create a Google Cloud project
1. Open **https://console.cloud.google.com** and sign in.
2. Top bar → project picker → **New Project** → name `shorts-autopilot` → **Create** → select it.

### A2. Enable the API
1. Menu → **APIs & Services → Library**.
2. Search **YouTube Data API v3** → **Enable**.
3. (Optional, for the analytics dashboard) also enable **YouTube Analytics API**.

### A3. OAuth consent screen
1. **APIs & Services → OAuth consent screen** (may be called *Google Auth Platform → Branding/Audience*).
2. User type: **External** → **Create**.
3. App name: anything (e.g. `Shorts Autopilot`), support email: yours, developer email: yours → **Save**.
4. Scopes: you can skip (the script requests them).
5. **Audience / Test users** → **Add users** → add the Google account(s) that own your YouTube channel(s).
6. **Important — publish the app:** *Audience* → **Publish app → Confirm** (status becomes *In production*).
   > In *Testing* mode Google expires the refresh token after **7 days** and your uploads stop. In production with an unverified app you'll just see an "unverified app" warning during login — click **Advanced → Go to … (unsafe)**. That's fine for your own channels.

### A4. Create the OAuth client
1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Desktop app** → name it → **Create**.
3. **Download JSON** → rename the file to **`client_secrets.json`** → put it in the project root (gitignored).

### A5. Log in once per channel
Make sure every channel is listed in `config.yaml`, then:

```bash
python auth_yt.py
```

For each channel a browser opens — **pick the Google account and then the exact YouTube channel/brand account** you want to upload to. A file `youtube_credentials_<Channel_Name>.json` is created for each (gitignored).

Optional analytics tokens (for the dashboard / retention tracker):
```bash
python setup_yt_analytics.py
```

### A6. Good to know
- **Quota:** each project gets 10,000 units/day; one upload costs ~1,600 units → about **6 uploads per day per project**. Running more channels? Create a second project + `client_secrets.json`, or request a quota increase (free) in *IAM & Admin → Quotas*.
- **Custom thumbnails** require a phone-verified channel: https://www.youtube.com/verify
- Turn on **"Altered or synthetic content"** disclosure where YouTube's policy requires it.

---

## Part B — Instagram + Facebook (Meta Graph API)

### B1. Accounts
1. A **Facebook Page** for the channel (facebook.com/pages/create).
2. An **Instagram Professional account** (Settings → Account type → switch to Professional/Creator or Business).
3. Link them: Instagram app → *Settings → Accounts Center* → add the Facebook account, **or** Facebook Page → *Settings → Linked accounts → Instagram → Connect*.

### B2. Create a Meta app
1. **https://developers.facebook.com** → *Get started* (register as developer, verify phone).
2. **My Apps → Create App** → use case **Other** → type **Business** → name it → **Create**.
3. In the app dashboard add products: **Instagram Graph API** (or "Instagram → API setup with Facebook login") and **Facebook Login for Business**.
4. *App settings → Basic*: note the **App ID** and **App Secret** (never share the secret).

### B3. Get a token with the right permissions
1. Open **https://developers.facebook.com/tools/explorer**.
2. Top right: **Meta App** = your app, **User or Page** = *User Token*.
3. **Add permissions**:
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `pages_manage_metadata`,
   `instagram_basic`, `instagram_content_publish`, `business_management`, `read_insights` (analytics, optional), `instagram_manage_insights` (optional)
4. **Generate Access Token** → approve every Page and Instagram account you want to use.
   This is a **short-lived user token** (~1 hour).

### B4. Make it permanent
Exchange it for a **long-lived user token** (60 days) — open this URL in your browser with your values:

```text
https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_LIVED_TOKEN
```

Then get the **Page tokens** (these generated from a long-lived user token **do not expire**):

```text
https://graph.facebook.com/v19.0/me/accounts?access_token=LONG_LIVED_USER_TOKEN
```

The response lists every Page with its `id` (**fb_page_id**) and `access_token` (**meta_access_token**).

> You can check any token at https://developers.facebook.com/tools/debug/accesstoken — *Expires: Never* is what you want.

### B5. Get the Instagram account ID
```text
https://graph.facebook.com/v19.0/PAGE_ID?fields=instagram_business_account&access_token=PAGE_TOKEN
```
`instagram_business_account.id` is your **ig_user_id** (a 17-digit number).

### B6. Put them in `config.yaml`
```yaml
  - name: Blade Archives
    platforms: [youtube, instagram, facebook]
    upload:
      fb_page_id: "1234567890123456"
      ig_user_id: "17841400000000000"
      meta_access_token: "EAAG...page token..."
```
Remove `facebook` from `platforms` if you only want Instagram (a new Page with no followers gets almost no Reels reach).

### B7. App mode
For your **own** Pages/Instagram accounts the app works in *Development* mode as long as your Facebook account has a role on the app (admin/developer). You only need Meta App Review if other people's accounts will use your app.

---

## Part C — TikTok (optional)

TikTok's Content Posting API only allows **public** posting after your developer app passes TikTok's audit; before that, uploads are private ("SELF_ONLY").

1. https://developers.tiktok.com → **Manage apps → Connect an app**. Add products **Login Kit** and **Content Posting API** (enable *Direct Post*). Scopes: `user.info.basic`, `video.publish`, `video.upload`.
2. Add a **Redirect URI** you control (any HTTPS page, e.g. a GitHub Pages site). Verify the domain/URL-prefix as TikTok requests.
3. Note the **Client Key** and **Client Secret**.
4. Tokens are stored in your Google Sheet (tab `TikTok_Tokens`) so refreshes persist between cloud runs — set up Google Sheets first ([guide 5](05-topics.md)).
5. Locally set env vars `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI`, then run:
   ```bash
   python tiktok_token_exchange.py
   ```
   Open the printed authorize link, log in, copy the `code` from the redirect URL, and paste it back.
6. Add `tiktok` to the channel's `platforms` and set the `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` GitHub secrets.

➡️ Next: [5 · Topics](05-topics.md)
