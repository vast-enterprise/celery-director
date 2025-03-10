import uuid
from sqlalchemy_utils import UUIDType

from director.extensions import db
from director.models import BaseModel, StatusType
from director.models.utils import JSONBType
from sqlalchemy.types import Enum, Boolean, String
from sqlalchemy import Column


def get_uuid():
    return str(uuid.uuid4())

class Workflow(BaseModel):
    __tablename__ = "celery_workflows"

    id = Column(
        UUIDType(binary=False), primary_key=True, nullable=False, default=get_uuid
    )
    tripo_task_id = Column(String(255), nullable=False, index=True)
    task_name = Column(String(255), nullable=False)
    model_version = Column(String(255), nullable=False)
    status = Column(Enum(StatusType), default=StatusType.pending, nullable=False)
    payload = Column(JSONBType, default={})
    periodic = Column(Boolean, default=False)
    comment = Column(String(255))

    def __str__(self):
        return f"{self.model_version}:{self.task_name}"

    def __repr__(self):
        return f"<Workflow {self.model_version}:{self.task_name}>"

    def to_dict(self, with_payload=True):
        d = super().to_dict()
        d.update(
            {
                "tripo_task_id": self.tripo_task_id,
                "task_name": self.task_name,
                "model_version": self.model_version,
                "fullname": f"{self.model_version}.{self.task_name}",
                "status": self.status.value,
                "periodic": self.periodic,
            }
        )
        if self.comment is not None:
            d["comment"] = self.comment
        if with_payload:
            d["payload"] = self.payload
        return d
