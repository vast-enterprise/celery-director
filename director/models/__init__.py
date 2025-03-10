import enum

from sqlalchemy import func
from sqlalchemy import Column, DateTime
from sqlalchemy.schema import MetaData
from sqlalchemy.ext.declarative import declarative_base


metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

Base = declarative_base(metadata=metadata)

class StatusType(enum.Enum):
    pending = "pending"
    progress = "progress"
    success = "success"
    error = "error"
    canceled = "canceled"


class BaseModel(Base):
    __abstract__ = True

    created_at = Column(
        DateTime(timezone=True), default=func.now(), nullable=False, index=True
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def commit(self, session):
        session.commit()

    def save(self, session):
        session.add(self)

    def to_dict(self):
        return {
            "id": self.id,
            "created": self.created_at.isoformat(),
            "updated": self.updated_at.isoformat(),
        }