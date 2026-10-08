                       
from datetime import datetime
from sqlalchemy.orm import joinedload
from app import db


class InterviewReport(db.Model):
    __tablename__ = 'interview_report'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey('interview_session.id', ondelete='CASCADE'), nullable=False, unique=True)
    content_analysis = db.Column(db.Text)
    expression_analysis = db.Column(db.Text)
    overall_score = db.Column(db.Float)
    highlights = db.Column(db.Text)
    improvements = db.Column(db.Text)
    suggestions = db.Column(db.Text)
    training_tasks = db.Column(db.Text)
    scoring_source = db.Column(db.String(32), nullable=False, default='rule')
    scoring_version = db.Column(db.String(32), nullable=False, default='mvp-v3')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'content_analysis': self.content_analysis,
            'expression_analysis': self.expression_analysis,
            'overall_score': self.overall_score,
            'highlights': self.highlights,
            'improvements': self.improvements,
            'suggestions': self.suggestions,
            'training_tasks': self.training_tasks,
            'scoring_source': self.scoring_source,
            'scoring_version': self.scoring_version,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<InterviewReport session_id={self.session_id} score={self.overall_score}>'

                                
    @classmethod
    def create(cls, session_id, content_analysis=None, expression_analysis=None, overall_score=None,
               highlights=None, improvements=None, suggestions=None,
               training_tasks=None,
               scoring_source='rule', scoring_version='mvp-v3', commit=True):
        obj = cls(
            session_id=session_id,
            content_analysis=content_analysis,
            expression_analysis=expression_analysis,
            overall_score=overall_score,
            highlights=highlights,
            improvements=improvements,
            suggestions=suggestions,
            training_tasks=training_tasks,
            scoring_source=scoring_source,
            scoring_version=scoring_version,
        )
        db.session.add(obj)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return obj

    @classmethod
    def get_by_id(cls, report_id):
        return cls.query.get(report_id)

    @classmethod
    def get_by_session_id(cls, session_id):
        return cls.query.filter_by(session_id=session_id).first()

    @classmethod
    def update_by_id(cls, report_id, **kwargs):
        obj = cls.query.get(report_id)
        if not obj:
            return None
        for k, v in kwargs.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        db.session.commit()
        return obj

    @classmethod
    def update_by_session(cls, session_id, **kwargs):
        obj = cls.query.filter_by(session_id=session_id).first()
        if not obj:
            return None
        for k, v in kwargs.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        db.session.commit()
        return obj

    @classmethod
    def list_by_user_id(cls, user_id, limit=100, mode=None,
                        position_code=None, scoring_version=None):
        from app.models import InterviewSession
        query = db.session.query(cls).options(joinedload(cls.session)).join(
            InterviewSession,
            cls.session_id == InterviewSession.id,
        ).filter(InterviewSession.user_id == user_id)
        if mode:
            query = query.filter(InterviewSession.mode == mode)
        if position_code:
            query = query.filter(InterviewSession.position_code == position_code)
        if scoring_version:
            query = query.filter(cls.scoring_version == scoring_version)
        return query.order_by(
            InterviewSession.started_at.desc()
        ).limit(limit).all()

    @classmethod
    def get_user_score_trend(cls, user_id, limit=50, mode='standard',
                             position_code=None, scoring_version=None):
        reports = cls.list_by_user_id(
            user_id,
            limit=limit,
            mode=mode,
            position_code=position_code,
            scoring_version=scoring_version,
        )
        return [(r.session.started_at, r.overall_score) for r in reversed(reports) if getattr(r, 'session', None)]
