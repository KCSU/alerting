"""Probe services, record results, and summarise history."""

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import Integer, cast, delete, func, select

from app.config import HISTORY_DAYS, TIMEOUT_SEC
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


def check(service: Service) -> Check:
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


def record(checks: list[Check]) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=HISTORY_DAYS)
    with session_factory.begin() as session:
        session.add_all(checks)
        session.execute(delete(Check).where(Check.checked_at < cutoff))


def load_services() -> list[Service]:
    with session_factory() as session:
        return list(session.scalars(select(Service).order_by(Service.id)))


def run_probes() -> None:
    with ThreadPoolExecutor() as pool:
        record(list(pool.map(check, load_services())))


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
