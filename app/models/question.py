                       
import json
import random
from datetime import datetime
from sqlalchemy import func
from app import db
from app.models.position import Position


class QuestionType:
    TECHNICAL = 'technical'
    PROJECT = 'project'
    SCENARIO = 'scenario'
    BEHAVIORAL = 'behavioral'


class Question(db.Model):
    __tablename__ = 'question'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    position_id = db.Column(db.Integer, db.ForeignKey('position.id'), nullable=False, index=True)
    type = db.Column(db.String(32), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    reference_answer = db.Column(db.Text)
    difficulty = db.Column(db.Integer, default=1)
    tags = db.Column(db.String(512))
    topic = db.Column(db.String(128))
    scoring_points = db.Column(db.Text)
    source = db.Column(db.String(128))
    review_status = db.Column(db.String(32), nullable=False, default='pending', index=True)
    reviewer = db.Column(db.String(128))
    reviewed_at = db.Column(db.DateTime)
    content_version = db.Column(db.Integer, nullable=False, default=1)
    is_core = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    deleted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    position = db.relationship('Position', backref=db.backref('questions', lazy='dynamic'))

    def to_dict(self):
        pos = self.position
        try:
            scoring_points = json.loads(self.scoring_points or '[]')
        except (TypeError, ValueError):
            scoring_points = []
        return {
            'id': self.id,
            'position_id': self.position_id,
            'position_code': pos.code if pos else None,
            'type': self.type,
            'content': self.content,
            'reference_answer': self.reference_answer,
            'difficulty': self.difficulty,
            'tags': self.tags,
            'topic': self.topic,
            'scoring_points': scoring_points,
            'source': self.source,
            'review_status': self.review_status,
            'reviewer': self.reviewer,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'content_version': self.content_version,
            'is_core': bool(self.is_core),
            'is_active': self.is_active,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Question {self.id} {(self.content or "")[:20]}>'

    @classmethod
    def create(cls, position_id, type_, content, reference_answer=None, difficulty=1,
               tags=None, topic=None, scoring_points=None, source=None,
               review_status='pending', reviewer=None, reviewed_at=None,
               content_version=1, is_core=False):
        if isinstance(scoring_points, (list, dict)):
            scoring_points = json.dumps(scoring_points, ensure_ascii=False)
        obj = cls(
            position_id=position_id,
            type=type_,
            content=(content or '').strip(),
            reference_answer=reference_answer,
            difficulty=difficulty,
            tags=tags,
            topic=topic,
            scoring_points=scoring_points,
            source=source,
            review_status=review_status,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            content_version=content_version,
            is_core=is_core,
        )
        db.session.add(obj)
        db.session.commit()
        return obj

    def get_scoring_points(self):
        try:
            value = json.loads(self.scoring_points or '[]')
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    @classmethod
    def get_by_id(cls, question_id):
        return cls.query.get(question_id)

    @classmethod
    def update_by_id(cls, question_id, **kwargs):
        obj = cls.query.get(question_id)
        if not obj:
            return None
        for k, v in kwargs.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        db.session.commit()
        return obj

    @classmethod
    def delete_by_id(cls, question_id):
        obj = cls.query.get(question_id)
        if not obj:
            return False
        obj.is_active = False
        obj.deleted_at = datetime.utcnow()
        db.session.commit()
        return True

    @classmethod
    def list_page(cls, position_code=None, position_id=None, type_=None, keyword=None,
                  page=1, per_page=20, include_inactive=False):
        q = cls.query
        if not include_inactive:
            q = q.filter(cls.is_active.is_(True))
        if position_code or position_id:
            q = q.join(Position, cls.position_id == Position.id)
        if position_code:
            q = q.filter(Position.code == position_code)
        if position_id:
            q = q.filter(cls.position_id == position_id)
        if type_:
            q = q.filter(cls.type == type_)
        kw = (keyword or '').strip()
        if kw:
            q = q.filter(cls.content.contains(kw))
        return q.order_by(cls.id.desc()).paginate(page=page, per_page=per_page)

    @classmethod
    def count(cls, position_code=None, position_id=None, type_=None, keyword=None):
        q = cls.query.filter(cls.is_active.is_(True))
        if position_code or position_id:
            q = q.join(Position, cls.position_id == Position.id)
        if position_code:
            q = q.filter(Position.code == position_code)
        if position_id:
            q = q.filter(cls.position_id == position_id)
        if type_:
            q = q.filter(cls.type == type_)
        kw = (keyword or '').strip()
        if kw:
            q = q.filter(cls.content.contains(kw))
        return q.count()

    @classmethod
    def random_sample_by_position(cls, position_code, limit):
        ids = [r[0] for r in db.session.query(cls.id).join(Position, cls.position_id == Position.id).filter(
            Position.code == position_code,
            cls.is_active.is_(True),
        ).all()]
        if not ids or limit <= 0:
            return []
        # Pseudo-randomness is intentional: this only varies question order and
        # is never used for credentials, tokens, or other security decisions.
        selected = ids if len(ids) <= limit else random.sample(ids, limit)  # nosec B311
        return cls.query.filter(cls.id.in_(selected)).order_by(cls.id).all()

    @classmethod
    def count_by_position(cls):
        rows = db.session.query(Position.code, func.count(cls.id)).join(
            Position, cls.position_id == Position.id
        ).filter(cls.is_active.is_(True)).group_by(Position.code).all()
        return dict(rows)

    @classmethod
    def count_by_type(cls):
        rows = db.session.query(cls.type, func.count(cls.id)).filter(
            cls.is_active.is_(True)
        ).group_by(cls.type).all()
        return dict(rows)
