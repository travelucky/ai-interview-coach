import json
from datetime import datetime

from app import db


class QuestionScore(db.Model):
    __tablename__ = 'question_score'
    __table_args__ = (
        db.UniqueConstraint('session_id', 'question_id', name='uq_question_score_session_question'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey('interview_session.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    question_id = db.Column(db.Integer, db.ForeignKey('question.id', ondelete='RESTRICT'), nullable=False, index=True)
    answer_message_id = db.Column(db.Integer, db.ForeignKey('interview_message.id', ondelete='CASCADE'))
    rule_score = db.Column(db.Float)
    llm_score = db.Column(db.Float)
    final_score = db.Column(db.Float, nullable=False)
    covered_points = db.Column(db.Text)
    missing_points = db.Column(db.Text)
    evidence = db.Column(db.Text)
    suggestion = db.Column(db.Text)
    knowledge_references = db.Column(db.Text)
    dimension_scores = db.Column(db.Text)
    scoring_source = db.Column(db.String(32), nullable=False, default='rule')
    scoring_version = db.Column(db.String(32), nullable=False, default='mvp-v3')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def _loads(value, default):
        try:
            parsed = json.loads(value or '')
            return parsed
        except (TypeError, ValueError):
            return default

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'question_id': self.question_id,
            'answer_message_id': self.answer_message_id,
            'rule_score': self.rule_score,
            'llm_score': self.llm_score,
            'final_score': self.final_score,
            'covered_points': self._loads(self.covered_points, []),
            'missing_points': self._loads(self.missing_points, []),
            'evidence': self._loads(self.evidence, []),
            'suggestion': self.suggestion,
            'knowledge_references': self._loads(self.knowledge_references, []),
            'dimension_scores': self._loads(self.dimension_scores, {}),
            'scoring_source': self.scoring_source,
            'scoring_version': self.scoring_version,
        }

    @classmethod
    def upsert(cls, session_id, question_id, commit=True, **values):
        row = cls.query.filter_by(session_id=session_id, question_id=question_id).first()
        if row is None:
            row = cls(session_id=session_id, question_id=question_id)
            db.session.add(row)
        for key, value in values.items():
            if key in {
                'covered_points', 'missing_points', 'evidence',
                'knowledge_references',
                'dimension_scores',
            } and not isinstance(value, str):
                default = {} if key == 'dimension_scores' else []
                value = json.dumps(value if value is not None else default, ensure_ascii=False)
            if hasattr(row, key):
                setattr(row, key, value)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return row

    @classmethod
    def list_by_session(cls, session_id):
        return cls.query.filter_by(session_id=session_id).order_by(cls.id.asc()).all()
