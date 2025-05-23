from director.extensions import db
from director.models import BaseModel
from director.models.utils import JSONBType


class Kafka(BaseModel):
    __tablename__ = "celery_kafka"

    backend_type = db.Column(
        db.String(255), primary_key=True, nullable=False, index=True, default="default"
    )
    topic = db.Column(JSONBType, nullable=False, default=list)
    partitions = db.Column(JSONBType, nullable=False, default=dict)
    data = db.Column(JSONBType, nullable=False, default=list)

    def __repr__(self):
        return f"<Kafka backend_type={self.backend_type}, topic={self.topic}, partitions={self.partitions}>"

    def to_dict(self):
        return {
            "backend_type": self.backend_type,
            "topic": self.topic,
            "partitions": self.partitions,
            "data": self.data,
        }


def get_kafka_dict():
    session = db.session
    try:
        ret = session.query(Kafka).all()
        return ret
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.remove()
