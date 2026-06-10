"""Notify: send email via Resend.

Uses the Resend HTTP API directly (stdlib only — no SDK dependency). Credentials
and addresses come from the environment (a local .env for dev, GitHub Secrets in CI):
    RESEND_API_KEY, EMAIL_TO, EMAIL_FROM

Milestone 3 sends a raw, ungrouped list of the day's new items. Once triage and
synthesis land, the briefing HTML is built upstream and just handed to send_email.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import urllib.error
import urllib.request

RESEND_ENDPOINT = "https://api.resend.com/emails"


def send_email(subject: str, body_html: str, *, to: str | None = None, sender: str | None = None) -> dict:
    """Send one email through Resend. Returns the parsed API response (includes the
    message id). Raises RuntimeError with the API's message on a non-2xx response."""
    api_key = os.environ["RESEND_API_KEY"]
    to = to or os.environ["EMAIL_TO"]
    sender = sender or os.environ["EMAIL_FROM"]

    payload = json.dumps(
        {"from": sender, "to": [to], "subject": subject, "html": body_html}
    ).encode("utf-8")
    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Resend is behind Cloudflare, which 403s the default Python-urllib
            # User-Agent (error 1010). A normal UA string clears it.
            "User-Agent": "dram-monitor/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise RuntimeError(f"Resend returned {error.code}: {detail}") from error


def render_raw_list_html(items: list[dict]) -> str:
    """Milestone 3 email body: the day's new items grouped by topic. No AI yet."""
    if not items:
        return "<p>Nothing material in the last 24h.</p>"

    by_topic: dict[str, list[dict]] = {}
    for item in items:
        by_topic.setdefault(item["topic"], []).append(item)

    parts: list[str] = []
    for topic in sorted(by_topic):
        parts.append(f"<h3>{html_lib.escape(topic.title())}</h3><ul>")
        for item in by_topic[topic]:
            title = html_lib.escape(item["title"])
            url = html_lib.escape(item["url"], quote=True)
            source = html_lib.escape(item["source"])
            parts.append(f'<li><a href="{url}">{title}</a> — <em>{source}</em></li>')
        parts.append("</ul>")
    return "\n".join(parts)
