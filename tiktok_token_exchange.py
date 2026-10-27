"""
TikTok Live Token Exchange Script
Run this after getting auth code from OAuth redirect.

Usage:
    python tiktok_token_exchange.py
"""
import os
import sys
import time
import requests
import yaml
from utils.tiktok_auth import get_sheets_service, write_tiktok_token

TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

# Credentials come from the environment — never hardcode them.
CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY", "")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
# Must exactly match a Redirect URI registered in your TikTok developer app.
REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI", "")
_CFG          = yaml.safe_load(open("config.yaml", encoding="utf-8"))
SHEET_ID      = _CFG.get("google_sheet_id", "")
SA_FILE       = "google_service_account.json"

if not (CLIENT_KEY and CLIENT_SECRET and REDIRECT_URI and SHEET_ID):
    sys.exit("Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI env vars "
             "and google_sheet_id in config.yaml first.")

CHANNELS = [c["name"] for c in _CFG.get("channels", []) if "tiktok" in c.get("platforms", [])]

def exchange_code(code: str) -> dict | None:
    """Exchange auth code for access + refresh token."""
    payload = {
        "client_key":    CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "code":          code.strip(),
        "grant_type":    "authorization_code",
        "redirect_uri":  REDIRECT_URI,
    }
    try:
        r = requests.post(
            TIKTOK_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        data = r.json()
        if r.status_code == 200 and "access_token" in data:
            return data
        else:
            print(f"  [ERROR] Token exchange failed: {data}")
            return None
    except Exception as e:
        print(f"  [ERROR] Request error: {e}")
        return None

def save_to_sheet(channel_name: str, token_data: dict, row_index: int):
    """Save token to Google Sheet TikTok_Tokens tab."""
    access_token  = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")
    expires_in    = token_data.get("expires_in", 86400)

    ok = write_tiktok_token(
        channel_name, SHEET_ID, row_index,
        access_token, refresh_token, expires_in, SA_FILE
    )
    if ok:
        print(f"  [OK] Saved to Google Sheet row {row_index}")
    else:
        print(f"  [WARN] Could not save to Sheet — printing token:")
        print(f"     Access:  {access_token}")
        print(f"     Refresh: {refresh_token}")

def get_next_row(channel_name: str) -> int:
    """Get existing row or next empty row in TikTok_Tokens sheet."""
    svc = get_sheets_service(SA_FILE)
    if not svc:
        return 2  # fallback
    try:
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range="TikTok_Tokens!A:A"
        ).execute()
        rows = result.get("values", [])
        for i, row in enumerate(rows):
            if row and row[0] == channel_name:
                return i + 1  # existing row
        return len(rows) + 1  # new row
    except Exception:
        return 2

def main():
    print("=" * 60)
    print("  TikTok Live Token Setup")
    print("=" * 60)
    print(f"\n  Client Key: {CLIENT_KEY}")
    print(f"  Redirect:   {REDIRECT_URI}\n")

    print("  AUTH URL (paste in browser for each account):")
    auth_url = (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={CLIENT_KEY}"
        f"&response_type=code"
        f"&scope=user.info.basic,video.publish,video.upload,user.info.profile,user.info.stats,video.list"
        f"&redirect_uri={REDIRECT_URI}"
        f"&state=live_auth"
    )
    print(f"\n  {auth_url}\n")
    print("-" * 60)

    print("\n  Available channels:")
    for i, ch in enumerate(CHANNELS, 1):
        print(f"   {i:2}. {ch}")

    while True:
        print("\n" + "-" * 60)
        ch_input = input("  Enter channel number (or 'q' to quit): ").strip()
        if ch_input.lower() == 'q':
            print("\n  Done! All tokens saved.")
            break

        try:
            ch_idx = int(ch_input) - 1
            channel_name = CHANNELS[ch_idx]
        except (ValueError, IndexError):
            print("  [ERROR] Invalid number. Try again.")
            continue

        print(f"\n  Channel: {channel_name}")
        print(f"  1. Open the auth URL above in browser")
        print(f"  2. Login with the TikTok account for '{channel_name}'")
        print(f"  3. After redirect, copy the 'code=' value from URL")
        code = input("  Paste code here: ").strip()

        # Clean code (sometimes has extra params)
        if "code=" in code:
            code = code.split("code=")[1].split("&")[0]

        print(f"  Exchanging code for token...")
        token_data = exchange_code(code)
        if not token_data:
            print("  [ERROR] Failed. Try again with a fresh code.")
            continue

        print(f"  [OK] Token received! open_id: {token_data.get('open_id', 'N/A')}")
        row = get_next_row(channel_name)
        save_to_sheet(channel_name, token_data, row)

if __name__ == "__main__":
    main()
