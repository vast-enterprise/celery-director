import  uuid

from sqlalchemy_utils import UUIDType

from director.extensions import db
from director.exceptions import UserNotFound
from director.models import BaseModel
from sqlalchemy.types import String
from sqlalchemy import Column


def get_uuid():
    return str(uuid.uuid4())

class User(BaseModel):
    __tablename__ = "celery_users"

    id = Column(
        UUIDType(binary=False), primary_key=True, nullable=False, default=get_uuid
    )
    username = Column(String(255), unique=True, nullable=False)
    password = Column(String(255), nullable=False)

    def __repr__(self):
        return f"<User {self.username}>"

    def update(self, session):
        user = session.query(User).filter_by(username=self.username).first()
        if not user:
            raise UserNotFound(f"User {self.username} not found")

        user.password = self.password

        self.commit()

    def delete(session, self):
        session.delete(self)

        self.commit()

    def to_dict(self):
        d = super().to_dict()
        d.update({"username": self.username, "password": self.password})
        return d
