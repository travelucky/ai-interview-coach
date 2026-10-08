import json
from datetime import datetime

from app import db


class TrainingTask(db.Model):
    __tablename__ = 'training_task'
    __table_args__ = (
        db.UniqueConstraint('source_session_id', 'task_id', name='uq_training_task_source_task'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    source_session_id = db.Column(db.Integer, db.ForeignKey('interview_session.id', ondelete='CASCADE'), nullable=False, index=True)
    task_id = db.Column(db.String(64), nullable=False)
    task_snapshot = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(24), nullable=False, default='todo', index=True)
    training_session_id = db.Column(db.Integer, nullable=True, index=True)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def snapshot(self):
        try:
            value = json.loads(self.task_snapshot or '{}')
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    def to_dict(self):
        result = self.snapshot()
        result.update({
            'id': self.task_id,
            'status': self.status,
            'training_session_id': self.training_session_id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        })
        return result

    @classmethod
    def create_many(cls, user_id, source_session_id, tasks, commit=True):
        rows = []
        for task in tasks or []:
            task_id = str(task.get('id') or '').strip()
            if not task_id:
                continue
            row = cls.query.filter_by(
                source_session_id=source_session_id,
                task_id=task_id,
            ).first()
            if row is None:
                row = cls(
                    user_id=user_id,
                    source_session_id=source_session_id,
                    task_id=task_id,
                    status='todo',
                )
                db.session.add(row)
            row.task_snapshot = json.dumps(task, ensure_ascii=False)
            rows.append(row)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return rows

    @classmethod
    def list_by_source(cls, source_session_id):
        return cls.query.filter_by(source_session_id=source_session_id).order_by(cls.id.asc()).all()

    def mark_started(self, training_session_id, commit=True):
        if self.status == 'completed':
            return self
        self.status = 'in_progress'
        self.training_session_id = training_session_id
        self.started_at = self.started_at or datetime.utcnow()
        if commit:
            db.session.commit()
        return self

    def mark_completed(self, commit=True):
        self.status = 'completed'
        self.completed_at = self.completed_at or datetime.utcnow()
        if commit:
            db.session.commit()
        return self
