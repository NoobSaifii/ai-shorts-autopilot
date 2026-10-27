"""
Build the GitHub Actions secrets from your local credential files.

    python scripts/make_secrets.py                      # writes github_secrets.txt (gitignored)
    python scripts/make_secrets.py --upload you/repo    # uploads them with the GitHub CLI (gh)

Files it looks for (in the repo root):
    config.yaml, gemini_keys.txt, google_service_account.json, client_secrets.json,
    youtube_credentials_*.json, youtube_analytics_*.json
Nothing is printed to the screen — values only go to the gitignored file or to gh.
"""
import argparse
import base64
import io
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "CONFIG_YAML_B64": "config.yaml",
    "GEMINI_KEYS_B64": "gemini_keys.txt",
    "GOOGLE_SA_B64": "google_service_account.json",
    "YT_CLIENT_SECRETS_B64": "client_secrets.json",
}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def build() -> tuple:
    secrets = {name: b64((ROOT / f).read_bytes()) for name, f in FILES.items() if (ROOT / f).exists()}
    tokens = sorted(ROOT.glob("youtube_credentials_*.json")) + sorted(ROOT.glob("youtube_analytics_*.json"))
    if tokens:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for t in tokens:
                z.write(t, t.name)
        secrets["YT_TOKENS_B64"] = b64(buf.getvalue())
    return secrets, tokens


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", metavar="OWNER/REPO", help="upload with `gh secret set` instead of writing a file")
    args = ap.parse_args()

    if not (ROOT / "config.yaml").exists():
        sys.exit("config.yaml not found — copy config.example.yaml to config.yaml and fill it in first.")

    secrets, tokens = build()
    print(f"Found {len(secrets)} secrets ({len(tokens)} YouTube token files zipped into YT_TOKENS_B64).")

    if args.upload:
        for name, value in secrets.items():
            r = subprocess.run(["gh", "secret", "set", name, "--repo", args.upload], input=value, text=True)
            print(("OK   " if r.returncode == 0 else "FAIL ") + name)
        return

    out = ROOT / "github_secrets.txt"
    out.write_text("".join(f"{k}:\n{v}\n\n" for k, v in secrets.items()), encoding="utf-8")
    print(f"Wrote {out.name} — copy each value into GitHub → Settings → Secrets → Actions.")
    print("Delete the file when done. It is gitignored, but don't leave secrets lying around.")


if __name__ == "__main__":
    main()
