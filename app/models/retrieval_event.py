import json
from datetime import datetime

from app import db


class RetrievalEvent(db.Model):
    __tablename__ = 'retrieval_event'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey('interview_session.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    question_id = db.Column(
        db.Integer,
        db.ForeignKey('question.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    use_case = db.Column(db.String(32), nullable=False)
    position_code = db.Column(db.String(64), nullable=False, index=True)
    query_excerpt = db.Column(db.String(1000), nullable=False)
    retrieval_version = db.Column(db.String(32), nullable=False)
    retrieval_method = db.Column(db.String(32), nullable=False)
    results = db.Column(db.Text, nullable=False, default='[]')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        try:
            results = json.loads(self.results or '[]')
        except (TypeError, ValueError):
            results = []
        return {
            'id': self.id,
            'session_id': self.session_id,
            'question_id': self.question_id,
            'use_case': self.use_case,
            'position_code': self.position_code,
            'query_excerpt': self.query_excerpt,
            'retrieval_version': self.retrieval_version,
            'retrieval_method': self.retrieval_method,
            'results': results,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def list_by_session(cls, session_id):
        return cls.query.filter_by(session_id=session_id).order_by(cls.id.asc()).all()
