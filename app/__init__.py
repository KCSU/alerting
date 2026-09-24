from datetime import UTC, datetime

from flask import Flask, render_template

from app.probe import DISPLAY_TZ, run_probes, summary


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route('/')
    def index() -> str:
        services = summary()
        checked = [s['latest'].checked_at for s in services if s['latest']]
        return render_template(
            'index.html',
            services=services,
            all_ok=all(s['ok'] for s in services),
            updated=max(checked).astimezone(DISPLAY_TZ) if checked else None,
            year=datetime.now(UTC).year,
        )

    @app.cli.command('probe')
    def probe() -> None:
        """Probe every service once and record the results."""
        run_probes()

    return app
