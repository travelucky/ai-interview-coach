import json
import math
from datetime import datetime, timedelta

from app import db


class SessionStatus:
    CREATED = 'created'
    INTERVIEWING = 'interviewing'
    SCORING = 'scoring'
    COMPLETED = 'completed'
    FAILED = 'failed'
    ABANDONED = 'abandoned'

    # Compatibility for older controller and database values.
    IN_PROGRESS = INTERVIEWING


ALLOWED_TRANSITIONS = {
    SessionStatus.CREATED: {SessionStatus.INTERVIEWING, SessionStatus.ABANDONED},
    SessionStatus.INTERVIEWING: {
        SessionStatus.SCORING,
        SessionStatus.ABANDONED,
    },
    SessionStatus.SCORING: {SessionStatus.COMPLETED, SessionStatus.FAILED},
    SessionStatus.FAILED: {SessionStatus.SCORING, SessionStatus.ABANDONED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.ABANDONED: set(),
}


class InterviewSession(db.Model):
    __tablename__ = 'interview_session'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='RESTRICT'), nullable=False, index=True)
    position_code = db.Column(db.String(64), nullable=False)
    question_ids = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.String(32),
        nullable=False,
        default=SessionStatus.INTERVIEWING,
        index=True,
    )
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    ended_at = db.Column(db.DateTime)  # Legacy alias retained for compatibility.
    completed_at = db.Column(db.DateTime)
    current_question_index = db.Column(db.Integer, nullable=False, default=0)
    answered_question_count = db.Column(db.Integer, nullable=False, default=0)
    total_question_count = db.Column(db.Integer, nullable=False, default=0)
    failure_reason = db.Column(db.Text)
    scoring_version = db.Column(db.String(32), nullable=False, default='mvp-v3')
    interview_state = db.Column(db.Text, nullable=True)
    mode = db.Column(db.String(32), nullable=False, default='standard', index=True)
    # SQLite self-referential DDL complicates clean teardown/migration, so this
    # reference is validated and deletion-protected in the service layer.
    source_session_id = db.Column(db.Integer, nullable=True, index=True)
    training_task_id = db.Column(db.String(64), nullable=True)

    messages = db.relationship(
        'InterviewMessage', backref='session', lazy='dynamic', order_by='InterviewMessage.sequence'
    )
    report = db.relationship('InterviewReport', backref='session', uselist=False)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'position_code': self.position_code,
            'question_ids': self.question_ids,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'current_question_index': self.current_question_index,
            'answered_question_count': self.answered_question_count,
            'total_question_count': self.total_question_count,
            'completion_ratio': self.completion_ratio,
            'failure_reason': self.failure_reason,
            'scoring_version': self.scoring_version,
            'mode': self.mode or 'standard',
            'source_session_id': self.source_session_id,
            'training_task_id': self.training_task_id,
        }

    def __repr__(self):
        return f'<InterviewSession {self.id} user={self.user_id} status={self.status}>'

    @property
    def completion_ratio(self):
        if not self.total_question_count:
            return 0.0
        return round(
            min(1.0, self.answered_question_count / self.total_question_count),
            4,
        )

    def minimum_required_answers(self, ratio=0.6):
        if self.total_question_count <= 0:
            return 1
        return max(1, math.ceil(self.total_question_count * ratio))

    def can_generate_report(self, ratio=0.6):
        return self.answered_question_count >= self.minimum_required_answers(ratio)

    @classmethod
    def create(cls, user_id, position_code, question_ids, mode='standard',
               source_session_id=None, training_task_id=None):
        if not isinstance(question_ids, list):
            question_ids = list(question_ids or [])
        obj = cls(
            user_id=user_id,
            position_code=position_code,
            question_ids=json.dumps(question_ids),
            status=SessionStatus.INTERVIEWING,
            total_question_count=len(question_ids),
            current_question_index=0,
            answered_question_count=0,
            scoring_version='mvp-v3',
            mode=mode or 'standard',
            source_session_id=source_session_id,
            training_task_id=training_task_id,
        )
        db.session.add(obj)
        db.session.commit()
        return obj

    @classmethod
    def get_by_id(cls, session_id):
        return db.session.get(cls, session_id)

    @classmethod
    def get_by_id_and_user(cls, session_id, user_id):
        return cls.query.filter_by(id=session_id, user_id=user_id).first()

    def transition_to(self, status, failure_reason=None, commit=True):
        if status == self.status:
            return self
        allowed = ALLOWED_TRANSITIONS.get(self.status, set())
        if status not in allowed:
            raise ValueError(f'Invalid session transition: {self.status} -> {status}')
        self.status = status
        self.failure_reason = failure_reason
        if status == SessionStatus.COMPLETED:
            now = datetime.utcnow()
            self.completed_at = now
            self.ended_at = now
        elif status == SessionStatus.ABANDONED:
            self.ended_at = datetime.utcnow()
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return self

    def record_progress(self, current_question_index, answered_question_count, state,
                        commit=True):
        self.current_question_index = max(0, int(current_question_index))
        self.answered_question_count = min(
            self.total_question_count,
            max(0, int(answered_question_count)),
        )
        self.interview_state = json.dumps(state) if state else None
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return self

    @classmethod
    def update_status(cls, session_id, status, ended_at=None):
        obj = cls.get_by_id(session_id)
        if not obj:
            return None
        if status == SessionStatus.COMPLETED:
            obj.transition_to(SessionStatus.COMPLETED)
        else:
            obj.status = status
            if ended_at is not None:
                obj.ended_at = ended_at
            db.session.commit()
        return obj

    @classmethod
    def complete(cls, session_id):
        obj = cls.get_by_id(session_id)
        return obj.transition_to(SessionStatus.COMPLETED) if obj else None

    def get_question_ids(self):
        try:
            values = json.loads(self.question_ids) if isinstance(self.question_ids, str) else self.question_ids
        except (TypeError, ValueError):
            return []
        return values if isinstance(values, list) else []

    def get_interview_state(self):
        fallback = {
            'current_question_index': self.current_question_index or 0,
            'follow_ups_this_question': 0,
        }
        if not self.interview_state:
            return fallback
        try:
            value = json.loads(self.interview_state)
            return value if isinstance(value, dict) else fallback
        except (TypeError, ValueError):
            return fallback

    def set_interview_state(self, state):
        self.interview_state = json.dumps(state) if state else None
        db.session.commit()

    @classmethod
    def list_by_user(cls, user_id, page=1, per_page=20, status=None):
        query = cls.query.filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)
        return query.order_by(cls.started_at.desc()).paginate(page=page, per_page=per_page)

    @classmethod
    def list_all_page(cls, page=1, per_page=20, status=None):
        query = cls.query
        if status:
            query = query.filter_by(status=status)
        return query.order_by(cls.started_at.desc()).paginate(page=page, per_page=per_page)

    @classmethod
    def count_total(cls):
        return cls.query.count()

    @classmethod
    def count_recent_days(cls, days=7):
        since = datetime.utcnow() - timedelta(days=days)
        return cls.query.filter(cls.started_at >= since).count()
