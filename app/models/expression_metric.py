import json
from datetime import datetime

from app import db


class ExpressionMetric(db.Model):
    __tablename__ = 'expression_metric'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    message_id = db.Column(
        db.Integer,
        db.ForeignKey('interview_message.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        index=True,
    )
    duration_ms = db.Column(db.Integer, nullable=False)
    character_count = db.Column(db.Integer, nullable=False, default=0)
    characters_per_minute = db.Column(db.Float, nullable=False, default=0)
    filler_word_count = db.Column(db.Integer, nullable=False, default=0)
    filler_words = db.Column(db.Text)
    repetition_count = db.Column(db.Integer, nullable=False, default=0)
    repetition_rate = db.Column(db.Float, nullable=False, default=0)
    acoustic_metrics = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    message = db.relationship('InterviewMessage', backref=db.backref('expression_metric', uselist=False))

    @staticmethod
    def _loads(value, default):
        try:
            return json.loads(value or '')
        except (TypeError, ValueError):
            return default

    def to_dict(self):
        acoustic = self._loads(self.acoustic_metrics, {})
        return {
            'message_id': self.message_id,
            'duration_ms': self.duration_ms,
            'duration_seconds': round(self.duration_ms / 1000, 1),
            'character_count': self.character_count,
            'characters_per_minute': self.characters_per_minute,
            'filler_word_count': self.filler_word_count,
            'filler_words': self._loads(self.filler_words, {}),
            'repetition_count': self.repetition_count,
            'repetition_rate': self.repetition_rate,
            'text_metrics': {
                'character_count': self.character_count,
                'characters_per_minute': self.characters_per_minute,
                'filler_word_count': self.filler_word_count,
                'filler_words': self._loads(self.filler_words, {}),
                'repetition_count': self.repetition_count,
                'repetition_rate': self.repetition_rate,
            },
            'acoustic_metrics': acoustic,
        }

    @classmethod
    def create_for_message(cls, message_id, values, commit=True):
        row = cls.query.filter_by(message_id=message_id).first()
        if row is None:
            row = cls(message_id=message_id)
            db.session.add(row)
        for key, value in values.items():
            if key in {'filler_words', 'acoustic_metrics'} and not isinstance(value, str):
                value = json.dumps(value or {}, ensure_ascii=False)
            if hasattr(row, key):
                setattr(row, key, value)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return row

    @classmethod
    def list_by_session(cls, session_id):
        from app.models.interview_message import InterviewMessage

        return (
            cls.query
            .join(InterviewMessage, cls.message_id == InterviewMessage.id)
            .filter(InterviewMessage.session_id == session_id)
            .order_by(InterviewMessage.sequence.asc())
            .all()
        )
