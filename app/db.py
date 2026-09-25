"""Database engine, session factory and models."""

from datetime import UTC, datetime

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    TypeDecorator,
    create_engine,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    QueryableAttribute,
    mapped_column,
    sessionmaker,
)

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
session_factory = sessionmaker(engine)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC (MySQL DATETIME has no zone); returns aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError('Naive datetime; pass an aware one')
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        return value and value.replace(tzinfo=UTC)


def utc_hour(column: QueryableAttribute[datetime]) -> ColumnElement[str]:
    """Truncate a UTCDateTime column to 'YYYY-MM-DD HH:00:00' (UTC)."""
    fmt = '%Y-%m-%d %H:00:00'
    if engine.dialect.name == 'sqlite':
        return func.strftime(fmt, column)
    return func.date_format(column, fmt)


class Base(DeclarativeBase):
    pass


class Service(Base):
    """A monitored service. Shown on the page in id order."""

    __tablename__ = 'services'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # Site URL, also the card link.
    url: Mapped[str] = mapped_column(String(255))
    # e.g.: /health, /healthz
    health_path: Mapped[str] = mapped_column(String(100))
    # When the last down alert was sent.
    last_alert_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Check(Base):
    __tablename__ = 'checks'
    __table_args__ = (
        Index('checks_service_id_checked_at', 'service_id', 'checked_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Deleting a service deletes its history.
    service_id: Mapped[int] = mapped_column(
        ForeignKey('services.id', ondelete='CASCADE')
    )
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    latency_ms: Mapped[int | None]
    # NULL means the check passed.
    error: Mapped[str | None] = mapped_column(String(255))

    @property
    def ok(self) -> bool:
        return self.error is None
