"""
Gmail notification helper.
Reads GMAIL_ADDRESS, GMAIL_APP_PASSWORD, and GMAIL_TO from environment variables.
Set them as GitHub Secrets (cloud) or in your shell (local testing).
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger("notifier")

def send(text: str) -> None:
    sender = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip().replace(" ", "")
    receiver = os.environ.get("GMAIL_TO", "").strip()

    if not sender or not password or not receiver:
        logger.warning("Gmail not configured (missing env vars) — skipping notification")
        return

    try:
        msg = MIMEText(text, "html")
        msg["Subject"] = "AI Video Pipeline Update"
        msg["From"] = sender
        msg["To"] = receiver

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.send_message(msg)
            
    except Exception as e:
        logger.warning(f"Gmail send failed: {e}")
