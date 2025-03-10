import uuid

from sqlalchemy_utils import UUIDType
from sqlalchemy.types import PickleType

from director.models import BaseModel, StatusType
from director.models.utils import JSONBType

from sqlalchemy.types import Enum, Boolean, String
from sqlalchemy import Column, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.orm import backref


def get_uuid():
    return str(uuid.uuid4())


class Task(BaseModel):
    __tablename__ = "celery_tasks"

    id = Column(
        UUIDType(binary=False), primary_key=True, nullable=False, default=get_uuid
    )
    key = Column(String(255), nullable=False)
    status = Column(Enum(StatusType), default=StatusType.pending, nullable=False)
    previous = Column(JSONBType, default=[])
    result = Column(PickleType)
    is_hook = Column(Boolean, default=False)
    data = Column(String(255), nullable=True)
    
    # Relationship
    workflow_id = Column(
        UUIDType(binary=False),
        ForeignKey("celery_workflows.id", ondelete="cascade"),
        nullable=False,
        index=True,
    )
    workflow = relationship(
        "Workflow", backref=backref("tasks", lazy=True), cascade="all,delete"
    )

    def __repr__(self):
        return f"<Task {self.key}>"

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "key": self.key,
                "status": self.status.value,
                "task": self.id,
                "previous": self.previous,
                "result": self.result,
                "is_hook": self.is_hook,
            }
        )
        return d
