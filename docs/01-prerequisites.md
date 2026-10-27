# 1 · Prerequisites & local install

You need a computer only for the **one-time setup** (logging in to YouTube, testing a video). After that everything runs in the cloud and your PC can stay off.

## Accounts you will create (all free)

| Account | Why | Link |
|---|---|---|
| GitHub | Hosts the code and runs the daily job | https://github.com/signup |
| Google (Gmail) | Gemini API key, YouTube API, optional Google Sheets | https://accounts.google.com |
| Cloudflare | Free AI image generation + R2 storage | https://dash.cloudflare.com/sign-up |
| Meta for Developers | Instagram + Facebook upload API | https://developers.facebook.com |
| cron-job.org | Triggers the workflow on time | https://console.cron-job.org/signup |

You also need: a **YouTube channel**, and (for Instagram/Facebook) a **Facebook Page** with an **Instagram Professional (Business or Creator) account** linked to it.

## Software to install

### Windows
1. **Python 3.11** — https://www.python.org/downloads/release/python-3119/
   During install **tick "Add python.exe to PATH"**.
2. **Git** — https://git-scm.com/download/win (keep defaults).
3. **FFmpeg** — open *PowerShell* and run:
   ```powershell
   winget install --id Gyan.FFmpeg -e
   ```
   Close and reopen PowerShell, then check: `ffmpeg -version`
4. **Node.js 22 LTS** (only for motion-graphic cards, optional) — https://nodejs.org
5. **eSpeak NG** (pronunciation fallback) — https://github.com/espeak-ng/espeak-ng/releases → download the `.msi`.

### macOS
```bash
brew install python@3.11 git ffmpeg espeak-ng node
```

### Ubuntu / Debian
```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv git ffmpeg espeak-ng
```

## Get the code

Click **Use this template → Create a new repository** at the top of this repo (recommended — gives you your own clean copy), or fork it. Then:

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
python -m venv .venv
```

Activate the virtual environment:

```powershell
.venv\Scripts\activate        # Windows
```
```bash
source .venv/bin/activate     # macOS / Linux
```

Install the Python packages:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

## Download the voice model (Kokoro, ~340 MB, one time)

Create a folder `kokoro_models` in the project root and put these two files in it:

- https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
- https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

(The folder is gitignored. GitHub Actions downloads it by itself.)

## Create your config

```bash
cp config.example.yaml config.yaml      # Windows: copy config.example.yaml config.yaml
```

Open `config.yaml` in any editor (VS Code, Notepad++). You'll fill it in during the next guides — every value to change is marked `# <-- CHANGE ME`.

## First test render (no upload)

Once you have finished guides 2 and 3 (Gemini key + one Cloudflare worker):

```bash
python daily_runner.py --channel "Blade Archives" --no-upload --keep-output
```

The finished video appears in `output/Blade Archives/<topic>/final/`. 🎉

➡️ Next: [2 · AI keys](02-ai-keys.md)
