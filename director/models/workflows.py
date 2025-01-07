from director.extensions import db
from director.models import BaseModel, StatusType
from director.models.utils import JSONBType


class Workflow(BaseModel):
    __tablename__ = "workflows"

    tripo_task_id = db.Column(db.String(255), nullable=False, index=True)
    task_name = db.Column(db.String(255), nullable=False)
    model_version = db.Column(db.String(255), nullable=False)
    status = db.Column(db.Enum(StatusType), default=StatusType.pending, nullable=False)
    payload = db.Column(JSONBType, default={})
    periodic = db.Column(db.Boolean, default=False)
    comment = db.Column(db.String(255))

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
