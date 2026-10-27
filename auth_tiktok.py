import os
import json
import time
import yaml
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

def setup_tiktok_tokens():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
        
    sheet_id = config.get("google_sheet_id")
    if not sheet_id:
        print("Error: google_sheet_id not found in config.yaml")
        return
        
    sa_file = "google_service_account.json"
    if not os.path.exists(sa_file):
        print("Error: google_service_account.json not found")
        return

    print("Connecting to Google Sheets...")
    creds = Credentials.from_service_account_file(sa_file, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service = build("sheets", "v4", credentials=creds)

    print("\n--- TikTok API Token Setup ---")
    print("For each channel, paste the JSON dictionary you got from the TikTok API.")
    print("It should contain 'access_token' and 'refresh_token'.")
    print("Type 'skip' to skip a channel.\n")

    for channel in config.get("channels", []):
        name = channel.get("name")
        tiktok_enabled = "tiktok" in channel.get("platforms", [])
        
        if not tiktok_enabled:
            continue
            
        print(f"\n[{name}]")
        user_input = input("Paste JSON token (or 'skip'): ").strip()
        
        if user_input.lower() == "skip" or not user_input:
            continue
            
        try:
            # Handle if the user pastes single quotes
            user_input = user_input.replace("'", '"')
            token_data = json.loads(user_input)
            
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 86400)
            
            if not access_token or not refresh_token:
                print("Error: JSON must contain access_token and refresh_token")
                continue
                
            expires_at = int(time.time()) + expires_in
            
            body = {
                "values": [[name, access_token, refresh_token, str(expires_at)]]
            }
            
            # Append row to TikTok_Tokens tab
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id, 
                range="TikTok_Tokens!A:D", 
                valueInputOption="USER_ENTERED", 
                insertDataOption="INSERT_ROWS",
                body=body
            ).execute()
            
            print(f"Successfully saved {name} token to Google Sheets!")
            
        except Exception as e:
            print(f"Error parsing JSON or saving to Sheets: {e}")

if __name__ == "__main__":
    setup_tiktok_tokens()
