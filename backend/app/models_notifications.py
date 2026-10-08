"""ORM-модель уведомлений."""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from .database import Base


class NotificationLevel(str, enum.Enum):
    info = "info"
    success = "success"
    warning = "warning"
    danger = "danger"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False, default="")
    level = Column(
        Enum(NotificationLevel),
        nullable=False,
        default=NotificationLevel.info,
    )
    link = Column(String(512), nullable=True)
    payload_json = Column(JSONB, nullable=False, default=dict)
    read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "read", "created_at"),
    )