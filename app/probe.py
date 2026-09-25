"""Probe services, record results, and summarise history."""

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import Integer, cast, delete, func, select, update
from sqlalchemy.orm import Session

from app import alert
from app.config import (
    ALERT_AFTER,
    ALERT_INTERVAL,
    CHECK_ATTEMPTS,
    HISTORY_DAYS,
    RECOVERED_AFTER,
    RETRY_DELAY_SEC,
    TIMEOUT_SEC,
)
from app.db import Check, Service, session_factory, utc_hour

# Stored times are UTC. The page shows UK days.
DISPLAY_TZ = ZoneInfo('Europe/London')


def evaluate(status_code: int, body: str) -> str | None:
    """Return None if the response is healthy, else a short reason."""
    if status_code != 200:
        return f'HTTP {status_code}'
    try:
        status = json.loads(body).get('status')
    except ValueError, AttributeError:
        return 'invalid health response'
    if status != 'ok':
        return f'status: {status}'[:255]
    return None


def health_url(service: Service) -> str:
    return service.url.rstrip('/') + '/' + service.health_path.lstrip('/')


def check_once(service: Service) -> Check:
    checked_at = datetime.now(UTC)
    start = time.monotonic()
    status_code = latency_ms = None
    try:
        resp = requests.get(health_url(service), timeout=TIMEOUT_SEC)
    except requests.RequestException as exc:
        error = type(exc).__name__
    else:
        status_code = resp.status_code
        latency_ms = int((time.monotonic() - start) * 1000)
        error = evaluate(resp.status_code, resp.text)
    return Check(
        service_id=service.id,
        checked_at=checked_at,
        status_code=status_code,
        latency_ms=latency_ms,
        error=error,
    )


def check(service: Service) -> Check:
    result = check_once(service)
    for _ in range(CHECK_ATTEMPTS - 1):
        if result.ok:
            break
        time.sleep(RETRY_DELAY_SEC)
        result = check_once(service)
    return result


def record(checks: list[Check]) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=HISTORY_DAYS)
    with session_factory.begin() as session:
        session.add_all(checks)
        session.execute(delete(Check).where(Check.checked_at < cutoff))


def load_services() -> list[Service]:
    with session_factory() as session:
        return list(session.scalars(select(Service).order_by(Service.id)))


def down_since(session: Session, service_id: int) -> datetime | None:
    """First failed check after the last passing one; None if currently up."""
    of_service = Check.service_id == service_id
    last_ok = session.scalar(
        select(func.max(Check.checked_at)).where(of_service, Check.error.is_(None))
    )
    first_failed = select(func.min(Check.checked_at)).where(of_service)
    if last_ok:
        first_failed = first_failed.where(Check.checked_at > last_ok)
    return session.scalar(first_failed)


def recovered_since(session: Session, service_id: int, t: datetime) -> bool:
    """Whether the service stayed up for RECOVERED_AFTER at some point after t."""
    rows = session.execute(
        select(Check.checked_at, Check.error)
        .where(Check.service_id == service_id, Check.checked_at > t)
        .order_by(Check.checked_at)
    )
    up_from = None
    for checked_at, error in rows:
        if error is None:
            up_from = up_from or checked_at
        elif up_from:
            if checked_at - up_from >= RECOVERED_AFTER:
                return True
            up_from = None
    return False


def alert_due(session: Session, service: Service, now: datetime) -> bool:
    since = down_since(session, service.id)
    if since is None or now - since < ALERT_AFTER:
        return False
    last = service.last_alert_at
    return (
        last is None
        or now - last >= ALERT_INTERVAL
        or recovered_since(session, service.id, last)
    )


def run_probes() -> None:
    services = load_services()
    with ThreadPoolExecutor() as pool:
        checks = list(pool.map(check, services))
    now = datetime.now(DISPLAY_TZ)
    errors = [c.error for c in checks]
    record(checks)
    with session_factory() as session:
        rows = [
            {
                'id': s.id,
                'name': s.name,
                'url': s.url,
                'error': error,
                'alert': alert_due(session, s, now),
            }
            for s, error in zip(services, errors, strict=True)
        ]
    alerted = [r['id'] for r in rows if r['alert']]
    if not alerted:
        return
    # Send first: if it fails, nothing is marked and the next run retries.
    alert.send(alert.message(rows, now))
    with session_factory.begin() as session:
        session.execute(
            update(Service).where(Service.id.in_(alerted)).values(last_alert_at=now)
        )


def summary() -> list[dict]:
    today = datetime.now(DISPLAY_TZ).date()
    dates = [today - timedelta(days=i) for i in reversed(range(HISTORY_DAYS))]
    start = datetime.combine(dates[0], datetime.min.time(), DISPLAY_TZ)
    hour = utc_hour(Check.checked_at).label('hour')
    services = load_services()
    with session_factory() as session:
        latest = {
            s.id: session.scalars(
                select(Check)
                .where(Check.service_id == s.id)
                .order_by(Check.checked_at.desc())
                .limit(1)
            ).first()
            for s in services
        }
        hourly = session.execute(
            select(
                Check.service_id,
                hour,
                func.sum(cast(Check.error.is_(None), Integer)),
                func.count(),
            )
            .where(Check.checked_at >= start)
            .group_by(Check.service_id, hour)
        ).all()

    up: Counter[tuple] = Counter()
    total: Counter[tuple] = Counter()
    for service_id, h, n_up, n in hourly:
        utc = datetime.fromisoformat(h).replace(tzinfo=UTC)
        key = service_id, utc.astimezone(DISPLAY_TZ).date()
        up[key] += int(n_up)
        total[key] += n

    result = []
    for s in services:
        last = latest[s.id]
        s_up = sum(up[s.id, d] for d in dates)
        s_total = sum(total[s.id, d] for d in dates)
        result.append(
            {
                'name': s.name,
                'url': s.url,
                'ok': bool(last and last.ok),
                'latest': last,
                'uptime': s_up / s_total if s_total else None,
                'days': [
                    (
                        f'{d.day} {d:%b %Y}',  # en-GB, e.g. 24 Sep 2026
                        up[s.id, d] / total[s.id, d] if total[s.id, d] else None,
                    )
                    for d in dates
                ],
            }
        )
    return result
