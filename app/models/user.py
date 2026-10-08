                       
from datetime import datetime
from app import db


class User(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='user')                
    display_name = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    interview_sessions = db.relationship(
        'InterviewSession', backref='user', lazy='dynamic', foreign_keys='InterviewSession.user_id'
    )

    def to_dict(self, include_sensitive=False):
        d = {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'display_name': self.display_name or self.username,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_sensitive:
            d['password_hash'] = self.password_hash
        return d

    def __repr__(self):
        return f'<User {self.username}>'

                                
    @classmethod
    def create(cls, username, password_hash, role='user', display_name=None):
        obj = cls(username=username, password_hash=password_hash, role=role, display_name=display_name)
        db.session.add(obj)
        db.session.commit()
        return obj

    @classmethod
    def get_by_id(cls, user_id):
        return cls.query.get(user_id)

    @classmethod
    def get_by_username(cls, username):
        return cls.query.filter_by(username=username).first()

    @classmethod
    def update_by_id(cls, user_id, **kwargs):
        obj = cls.query.get(user_id)
        if not obj:
            return None
        for k, v in kwargs.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        db.session.commit()
        return obj

    @classmethod
    def delete_by_id(cls, user_id):
        obj = cls.query.get(user_id)
        if not obj:
            return False
        from app.models import InterviewSession
        if InterviewSession.query.filter_by(user_id=user_id).first() is not None:
            return False
        db.session.delete(obj)
        db.session.commit()
        return True

    @classmethod
    def list_page(cls, role=None, page=1, per_page=20):
        q = cls.query
        if role:
            q = q.filter_by(role=role)
        return q.order_by(cls.id.desc()).paginate(page=page, per_page=per_page)

    @classmethod
    def count(cls, role=None):
        q = cls.query
        if role:
            q = q.filter_by(role=role)
        return q.count()
