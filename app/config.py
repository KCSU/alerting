import os

from dotenv import load_dotenv

load_dotenv()


def required_from_env(key: str) -> str:
    value = os.getenv(key)
    if value is None:
        raise ValueError(f'Missing required environment variable: {key}')
    return value


# MySQL in production (/societies is NFS, where SQLite locking is unreliable),
# e.g. mysql+pymysql://user:password@host:3306/alerting. Tests use sqlite://.
DATABASE_URL = required_from_env('DATABASE_URL')

TIMEOUT_SEC = 10
HISTORY_DAYS = 90
