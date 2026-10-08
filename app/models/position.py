                       
from datetime import datetime
from app import db


class Position(db.Model):
    __tablename__ = 'position'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Position {self.code}>'

    @classmethod
    def create(cls, code, name, description=None):
        code = (code or '').strip()
        name = (name or '').strip()
        obj = cls(code=code, name=name, description=description)
        db.session.add(obj)
        db.session.commit()
        return obj

    @classmethod
    def get_by_id(cls, position_id):
        return cls.query.get(position_id)

    @classmethod
    def get_by_code(cls, code):
        return cls.query.filter_by(code=code).first()

    @classmethod
    def update_by_id(cls, position_id, **kwargs):
        obj = cls.query.get(position_id)
        if not obj:
            return None
        for k, v in kwargs.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        db.session.commit()
        return obj

    @classmethod
    def delete_by_id(cls, position_id):
        obj = cls.query.get(position_id)
        if not obj:
            return False
        from app.models import Question
        if Question.query.filter_by(position_id=position_id).first() is not None:
            return False
        db.session.delete(obj)
        db.session.commit()
        return True

    @classmethod
    def list_all(cls):
        return cls.query.order_by(cls.id.asc()).all()
