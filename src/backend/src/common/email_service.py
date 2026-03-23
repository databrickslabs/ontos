"""
Email delivery service supporting SMTP and HTTP API providers.

Reads configuration from the Settings DB (EmailConfig).
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional

from src.common.logging import get_logger

logger = get_logger(__name__)


class EmailService:
    """Send emails via SMTP or HTTP API provider."""

    def __init__(
        self,
        *,
        provider: str = "smtp",
        from_address: str = "",
        from_name: str = "Ontos Notifications",
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_username: str = "",
        smtp_password: str = "",
        smtp_use_tls: bool = True,
        api_key: str = "",
        api_endpoint: str = "",
    ):
        self.provider = provider
        self.from_address = from_address
        self.from_name = from_name
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.smtp_use_tls = smtp_use_tls
        self.api_key = api_key
        self.api_endpoint = api_endpoint

    @classmethod
    def from_settings(cls, db) -> Optional["EmailService"]:
        """Create an EmailService from the settings stored in the DB.

        Returns None when email is not configured or disabled.
        """
        from src.db_models.app_settings import AppSettingDb as SettingDb
        import json

        row = db.query(SettingDb).filter(SettingDb.key == "email_config").first()
        if not row:
            return None
        try:
            config = json.loads(row.value) if isinstance(row.value, str) else row.value
        except Exception:
            return None

        if not config.get("enabled", False):
            return None

        return cls(
            provider=config.get("provider", "smtp"),
            from_address=config.get("from_address", ""),
            from_name=config.get("from_name", "Ontos Notifications"),
            smtp_host=config.get("smtp_host", ""),
            smtp_port=config.get("smtp_port", 587),
            smtp_username=config.get("smtp_username", ""),
            smtp_password=config.get("smtp_password", ""),
            smtp_use_tls=config.get("smtp_use_tls", True),
            api_key=config.get("api_key", ""),
            api_endpoint=config.get("api_endpoint", ""),
        )

    def send(
        self,
        to: List[str],
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> bool:
        """Send an email. Returns True on success."""
        if self.provider == "smtp":
            return self._send_smtp(to, subject, body_text, body_html)
        elif self.provider in ("sendgrid", "webhook"):
            return self._send_api(to, subject, body_text, body_html)
        else:
            logger.error(f"Unknown email provider: {self.provider}")
            return False

    # ------------------------------------------------------------------
    def _send_smtp(
        self,
        to: List[str],
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> bool:
        if not self.smtp_host or not self.from_address:
            logger.warning("SMTP not configured — skipping email send")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_address}>"
        msg["To"] = ", ".join(to)

        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        try:
            if self.smtp_use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)

            if self.smtp_username:
                server.login(self.smtp_username, self.smtp_password)

            server.sendmail(self.from_address, to, msg.as_string())
            server.quit()
            logger.info(f"Email sent to {to} via SMTP")
            return True
        except Exception as e:
            logger.exception(f"SMTP send failed: {e}")
            return False

    # ------------------------------------------------------------------
    def _send_api(
        self,
        to: List[str],
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> bool:
        """Send via an HTTP API (SendGrid-compatible or generic webhook)."""
        import json
        import urllib.request
        import urllib.error

        if not self.api_key or not self.api_endpoint:
            logger.warning("API email provider not configured — skipping")
            return False

        payload = {
            "personalizations": [{"to": [{"email": addr} for addr in to]}],
            "from": {"email": self.from_address, "name": self.from_name},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body_text}],
        }
        if body_html:
            payload["content"].append({"type": "text/html", "value": body_html})

        req = urllib.request.Request(
            self.api_endpoint,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                logger.info(f"Email API response: {resp.status}")
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as e:
            logger.exception(f"Email API request failed ({e.code}): {e.read()}")
            return False
        except Exception as e:
            logger.exception(f"Email API request error: {e}")
            return False
