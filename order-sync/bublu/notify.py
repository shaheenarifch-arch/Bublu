"""Alerts: always logged; emailed when SMTP settings are present."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import Settings

log = logging.getLogger("bublu")


class Notifier:
    def __init__(self, settings: Settings):
        self.s = settings
        self.sent: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> None:
        subject = f"[BUBLU] {subject}"
        self.sent.append((subject, body))
        log.info("%s\n%s", subject, body)
        if not (self.s.smtp_host and self.s.alert_email_to):
            return
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.s.smtp_from or self.s.smtp_user
        msg["To"] = self.s.alert_email_to
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if self.s.smtp_user:
                    smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(msg)
        except Exception as exc:  # never let email problems stop order processing
            log.error("alert email failed: %s", exc)
