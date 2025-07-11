import enum

import pytz
from datetime import datetime

from director.extensions import db


class StatusType(enum.Enum):
    pending = "pending"
    progress = "progress"
    success = "success"
    error = "error"
    canceled = "canceled"


class BaseModel(db.Model):
    __abstract__ = True

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(pytz.UTC),
        nullable=False,
        index=True,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )

    def commit(self):
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        # finally:
        #     # 暂时加上 close
        #     db.session.close()

    def save(self):
        db.session.add(self)
        self.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "created": self.created_at.isoformat(),
            "updated": self.updated_at.isoformat(),
        }
