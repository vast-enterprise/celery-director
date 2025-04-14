import uuid

from director.extensions import db
from sqlalchemy_utils import UUIDType
from director.models import BaseModel
from director.models.utils import JSONBType



def get_uuid():
    return str(uuid.uuid4())


class Kafka(BaseModel):
    __tablename__ = "celery_kafka"

    id = db.Column(UUIDType(binary=False), primary_key=True, nullable=False, default=get_uuid)
    topic = db.Column(db.String(255), nullable=False)
    partitions = db.Column(JSONBType, nullable=False, default=list)  # 默认是空 list
    data = db.Column(JSONBType, nullable=False, default=list)  # 默认是空 list

    def __repr__(self):
        return f"<Kafka topic={self.topic} partitions={self.partitions}>"

    def to_dict(self):
        return {
            "id": self.id,
            "topic": self.topic,
            "partitions": self.partitions,
            "data": self.data,
        }