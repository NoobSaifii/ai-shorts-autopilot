import os
import time
import logging
import requests
import yaml
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

logger = logging.getLogger("utils.tiktok_auth")
TIKTOK_OAUTH_URL = "https://open.tiktokapis.com/v2/oauth/token/"

def get_sheets_service(sa_file="google_service_account.json"):
    if not sa_file or not os.path.exists(sa_file):
        return None
    try:
        creds = Credentials.from_service_account_file(
            sa_file, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to build Sheets service: {e}")
        return None

def get_tiktok_client_credentials():
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    return client_key, client_secret

def read_tiktok_token(channel_name: str, sheet_id: str, sa_file: str = "google_service_account.json"):
    service = get_sheets_service(sa_file)
    if not service:
        logger.error("Missing Google Sheets config for TikTok tokens.")
        return None
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range="TikTok_Tokens!A:D"
        ).execute()
        rows = result.get("values", [])
        for i, row in enumerate(rows):
            if row and row[0] == channel_name:
                return {
                    "row_index": i + 1,
                    "access_token": row[1] if len(row) > 1 else "",
                    "refresh_token": row[2] if len(row) > 2 else "",
                    "expires_at": int(row[3]) if len(row) > 3 and row[3] else 0
                }
    except Exception as e:
        logger.error(f"Failed to read TikTok_Tokens sheet: {e}")
    return None

def write_tiktok_token(channel_name: str, sheet_id: str, row_index: int, access_token: str, refresh_token: str, expires_in: int, sa_file: str = "google_service_account.json"):
    service = get_sheets_service(sa_file)
    if not service:
        return False
    expires_at = int(time.time()) + expires_in
    body = {
        "values": [[channel_name, access_token, refresh_token, str(expires_at)]]
    }
    range_name = f"TikTok_Tokens!A{row_index}:D{row_index}"
    try:
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        logger.info(f"Successfully saved new TikTok token to row {row_index}.")
        return True
    except Exception as e:
        logger.error(f"Failed to save TikTok token: {e}")
        return False

def refresh_tiktok_token(channel_name: str, sheet_id: str, token_data: dict, sa_file: str = "google_service_account.json"):
    client_key, client_secret = get_tiktok_client_credentials()
    if not client_key or not client_secret:
        logger.error("TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET missing.")
        return None
        
    logger.info(f"Refreshing TikTok access token for {channel_name}...")
    payload = {
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": token_data["refresh_token"]
    }
    try:
        r = requests.post(TIKTOK_OAUTH_URL, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        data = r.json()
        if r.status_code == 200 and "access_token" in data:
            new_access = data["access_token"]
            new_refresh = data.get("refresh_token", token_data["refresh_token"])
            expires_in = data.get("expires_in", 86400)
            write_tiktok_token(channel_name, sheet_id, token_data["row_index"], new_access, new_refresh, expires_in, sa_file)
            return new_access
        else:
            logger.error(f"TikTok token refresh failed: {data}")
            return None
    except Exception as e:
        logger.error(f"TikTok token refresh exception: {e}")
        return None

def get_valid_tiktok_access_token(channel_name: str, sheet_id: str, sa_file: str = "google_service_account.json"):
    token_data = read_tiktok_token(channel_name, sheet_id, sa_file)
    if not token_data or not token_data.get("refresh_token"):
        logger.error(f"No TikTok refresh token found for channel '{channel_name}'.")
        return None
    if token_data.get("access_token") and token_data.get("expires_at", 0) > time.time() + 600:
        return token_data["access_token"]
    return refresh_tiktok_token(channel_name, sheet_id, token_data, sa_file)
