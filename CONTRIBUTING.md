# Contributing

Thanks for helping! 🎉

1. Fork the repo and create a branch: `git checkout -b feat/my-change`
2. Keep changes focused; match the existing code style.
3. Test locally without uploading:
   `python daily_runner.py --channel "<your channel>" --no-upload --keep-output`
4. Open a pull request describing **what** changed and **why**.

**Never commit secrets.** `config.yaml`, `client_secrets.json`, `youtube_credentials_*.json`,
`google_service_account.json` and `gemini_keys.txt` must stay local. The Gitleaks check will
fail your PR if a key is detected.

Good first contributions: new channel prompts in `prompts/`, more voices in
`modules/tts_edge.py`, docs improvements, translations of the setup guide.
