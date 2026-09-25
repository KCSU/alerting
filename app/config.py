import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


def required_from_env(key: str) -> str:
    value = os.getenv(key)
    if value is None:
        raise ValueError(f'Missing required environment variable: {key}')
    return value


DATABASE_URL = required_from_env('DATABASE_URL')

TIMEOUT_SEC = 10
# Tries per check before recording a failure, so one blip isn't an outage.
CHECK_ATTEMPTS = 3
RETRY_DELAY_SEC = 5
HISTORY_DAYS = 90

STATUS_URL = 'https://status.kcsu.org.uk/'
ALERT_TO = 'computing@kcsu.org.uk'
ALERT_FROM = 'KCSU Status Monitor <computing@kcsu.org.uk>'
SMTP_HOST = 'localhost'
# Debounce email sending.
ALERT_INTERVAL = timedelta(hours=6)
# Alert only once a service has been down this long.
ALERT_AFTER = timedelta(minutes=10)
# Consider two outages of the same service to be different if there was this much green
# in between.
RECOVERED_AFTER = timedelta(minutes=30)
