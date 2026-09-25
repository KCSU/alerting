"""Build and send the outage alert email."""

import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.config import ALERT_FROM, ALERT_TO, SMTP_HOST, STATUS_URL

APP_DIR = Path(__file__).parent
templates = Environment(loader=FileSystemLoader(APP_DIR / 'templates'), autoescape=True)


def headline(rows: list[dict]) -> str:
    names = [r['name'] for r in rows if r['alert']]
    return f'Outage of service(s) detected: {", ".join(names)}'


def message(rows: list[dict], now: datetime) -> EmailMessage:
    title = headline(rows)
    alerted = [r for r in rows if r['alert']]

    msg = EmailMessage()
    msg['Subject'] = f'[KCSU Alerting] {title}'
    msg['From'] = ALERT_FROM
    msg['To'] = ALERT_TO
    text = '\n'.join(f'{r["name"]}: {r["error"]}' for r in alerted)
    msg.set_content(f'{title}\n\n{text}\n\nLive status: {STATUS_URL}\n')
    logo_cid = make_msgid()
    html = templates.get_template('alert_email.html').render(
        title=title,
        alerted=alerted,
        rows=rows,
        now=now,
        status_url=STATUS_URL,
        logo_cid=logo_cid[1:-1],
    )
    msg.add_alternative(html, subtype='html')
    html_part = msg.get_body(('html',))
    assert html_part is not None
    html_part.add_related(
        (APP_DIR / 'static' / 'email-logo.png').read_bytes(),
        'image',
        'png',
        cid=logo_cid,
    )
    return msg


def send(msg: EmailMessage) -> None:
    with smtplib.SMTP(SMTP_HOST) as smtp:
        smtp.send_message(msg)
