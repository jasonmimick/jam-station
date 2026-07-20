"""Sending email, portably.

THE PORTABILITY ANSWER IS SMTP. Every provider speaks it — Gmail, Fastmail, iCloud, Resend,
Postmark, SES, Mailgun, a self-hosted Postfix. Support SMTP and you support all of them,
forever. Swapping providers is three env vars and zero code.

⚠️  DO NOT SEND DIRECTLY FROM THE MAC-MINI. Residential IPs are permanently blocklisted, most
    ISPs block outbound port 25, and with no SPF/DKIM you land in spam. This is not a
    contradiction with "portable" — the resolution is:

        PORTABLE INTERFACE (smtp)  ·  REPUTABLE TRANSPORT (a provider)  ·  AUTHENTICATED
        DOMAIN (runslab.run, whose DNS is already on Cloudflare)

Backends:
    console  — prints the mail. The DEFAULT, and it makes the entire auth flow testable
               with no credentials at all. The link and code are right there in the log.
    smtp     — the real one. Point it at Gmail (app password), Resend, Postmark, anything.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from . import config

log = logging.getLogger("mail")


def send(to: str, subject: str, body: str, cc: str = "") -> bool:
    if config.MAIL_BACKEND == "smtp":
        return _smtp(to, subject, body, cc)
    return _console(to, subject, body, cc)


def _console(to: str, subject: str, body: str, cc: str = "") -> bool:
    # Not a stub — this is a working backend. With no SMTP configured you can still run the
    # whole invite/approve/sign-in flow; the magic link and the code are printed here.
    log.warning(
        "\n"
        "┌─ EMAIL (console backend — set MAIL_BACKEND=smtp to actually send) ─────────\n"
        "│ To:      %s\n"
        "│ Cc:      %s\n"
        "│ Subject: %s\n"
        "├───────────────────────────────────────────────────────────────────────────\n"
        "%s\n"
        "└───────────────────────────────────────────────────────────────────────────",
        to, cc or "—", subject, "\n".join("│ " + ln for ln in body.splitlines()),
    )
    return True


def _smtp(to: str, subject: str, body: str, cc: str = "") -> bool:
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM
    msg["To"] = to
    if cc:
        msg["Cc"] = cc            # send_message adds Cc addresses to the envelope automatically
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        if config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, 465,
                                  context=ssl.create_default_context(), timeout=20) as s:
                if config.SMTP_USER:
                    s.login(config.SMTP_USER, config.SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                if config.SMTP_USER:
                    s.login(config.SMTP_USER, config.SMTP_PASS)
                s.send_message(msg)
        return True
    except Exception as e:                      # never let a mail failure 500 a request
        log.error("smtp send to %s failed: %s", to, e)
        return False
