import yaml
import json
import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

BASE_DIR = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    config = yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8"))
    channels = config.get("channels", [])
    client_secrets = str(BASE_DIR / "client_secrets.json")

    print(f"\n{'='*55}")
    print(f"  YouTube Upload Setup — {len(channels)} channels")
    print(f"{'='*55}\n")

    for ch in channels:
        name = ch["name"]
        safe = name.replace(" ", "_")
        out_file = BASE_DIR / f"youtube_credentials_{safe}.json"

        if out_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(out_file), SCOPES)
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    out_file.write_text(creds.to_json())
                if creds.valid:
                    print(f"  ✓  {name} — already authorized")
                    continue
            except Exception:
                pass

        print(f"\n  ► Authorizing: {name}")
        print(f"    A browser window will open — log in as the channel owner.")
        input(f"    Press Enter to open browser for '{name}'...")

        flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
        creds = flow.run_local_server(port=0)
        out_file.write_text(creds.to_json())
        print(f"    Saved: {out_file.name}")

    print(f"\n{'='*55}")
    print("  All channels authorized for Upload.")
    print("  Remember to copy the new base64 strings to GitHub Secrets!")
    print(f"{'='*55}\n")

if __name__ == "__main__":
    main()
