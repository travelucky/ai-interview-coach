                       
from datetime import datetime
from app import db


class MessageRole:
    ASSISTANT = 'assistant'
    USER = 'user'


class MessageKind:
    QUESTION = 'question'
    FOLLOW_UP = 'follow_up'
    ANSWER = 'answer'
    SYSTEM = 'system'


class InterviewMessage(db.Model):
    __tablename__ = 'interview_message'
    __table_args__ = (
        db.UniqueConstraint(
            'session_id',
            'client_request_id',
            name='uq_interview_message_session_request',
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey('interview_session.id', ondelete='CASCADE'), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sequence = db.Column(db.Integer, nullable=False)
    client_request_id = db.Column(db.String(64), nullable=True, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id', ondelete='RESTRICT'), nullable=True, index=True)
    message_kind = db.Column(db.String(32), nullable=True, index=True)
    answer_source = db.Column(db.String(16), nullable=True)
    raw_transcript = db.Column(db.Text, nullable=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'role': self.role,
            'content': self.content,
            'sequence': self.sequence,
            'client_request_id': self.client_request_id,
            'question_id': self.question_id,
            'message_kind': self.message_kind,
            'answer_source': self.answer_source,
            'raw_transcript': self.raw_transcript,
            'edited_at': self.edited_at.isoformat() if self.edited_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<InterviewMessage {self.id} {self.role}>'

                                
    @classmethod
    def create(cls, session_id, role, content, sequence, client_request_id=None,
               question_id=None, message_kind=None, answer_source=None,
               raw_transcript=None, commit=True):
        obj = cls(
            session_id=session_id,
            role=role,
            content=content,
            sequence=sequence,
            client_request_id=client_request_id,
            question_id=question_id,
            message_kind=message_kind,
            answer_source=answer_source,
            raw_transcript=raw_transcript,
        )
        db.session.add(obj)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return obj

    @classmethod
    def get_next_sequence(cls, session_id):
        r = db.session.query(db.func.max(cls.sequence)).filter_by(session_id=session_id).scalar()
        return (r or 0) + 1

    @classmethod
    def list_by_session(cls, session_id, order_asc=True):
        q = cls.query.filter_by(session_id=session_id)
        q = q.order_by(cls.sequence.asc() if order_asc else cls.sequence.desc())
        return q.all()

    @classmethod
    def get_by_client_request_id(cls, session_id, client_request_id):
        if not client_request_id:
            return None
        return cls.query.filter_by(
            session_id=session_id,
            client_request_id=client_request_id,
            role=MessageRole.USER,
        ).first()
