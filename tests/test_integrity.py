import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import db


def _login_admin(client):
    client.post('/api/auth/logout')
    response = client.post(
        '/api/auth/login',
        json={'username': 'admin', 'password': 'AdminPass123!'},
    )
    assert response.status_code == 200


def test_sqlite_foreign_keys_are_enabled_and_reject_orphans(app):
    from app.models import InterviewMessage
    from app.models.interview_message import MessageKind, MessageRole

    with app.app_context():
        assert db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
        db.session.add(InterviewMessage(
            session_id=999999,
            role=MessageRole.USER,
            content='孤立消息',
            sequence=1,
            message_kind=MessageKind.ANSWER,
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_legacy_database_schema_upgrade_is_idempotent(tmp_path):
    from app import create_app
    from app.migrations import ensure_mvp_schema

    database_path = tmp_path / 'legacy.db'
    legacy_app = create_app(
        'testing',
        {
            'SECRET_KEY': 'legacy-test-key',
            'SECRET_KEY_IS_EPHEMERAL': False,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database_path}',
        },
    )
    with legacy_app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE interview_session ('
                'id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, '
                'position_code VARCHAR(64) NOT NULL, question_ids TEXT NOT NULL, '
                "status VARCHAR(32) NOT NULL DEFAULT 'in_progress', "
                'started_at DATETIME, ended_at DATETIME, interview_state TEXT)'
            ))
            connection.execute(text(
                'CREATE TABLE interview_message ('
                'id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, '
                'role VARCHAR(16) NOT NULL, content TEXT NOT NULL, '
                'sequence INTEGER NOT NULL, created_at DATETIME)'
            ))
            connection.execute(text(
                'CREATE TABLE question ('
                'id INTEGER PRIMARY KEY, position_id INTEGER NOT NULL, '
                'type VARCHAR(32) NOT NULL, content TEXT NOT NULL, '
                'reference_answer TEXT, difficulty INTEGER, tags VARCHAR(512), '
                'created_at DATETIME, updated_at DATETIME)'
            ))
        applied = ensure_mvp_schema()
        assert 'question.is_active' in applied
        assert 'question.deleted_at' in applied
        assert 'interview_message.raw_transcript' in applied
        assert ensure_mvp_schema() == []
        table_names = {
            row[0] for row in db.session.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }
        assert 'retrieval_event' in table_names
        assert 'training_task' in table_names
        question_columns = {
            row[1] for row in db.session.execute(text('PRAGMA table_info(question)'))
        }
        assert {
            'is_active', 'deleted_at', 'topic', 'scoring_points', 'source',
            'review_status', 'reviewer', 'reviewed_at', 'content_version',
            'is_core',
        } <= question_columns
        message_columns = {
            row[1] for row in db.session.execute(
                text('PRAGMA table_info(interview_message)')
            )
        }
        assert {'answer_source', 'raw_transcript', 'edited_at'} <= message_columns
        db.session.remove()
        db.engine.dispose()


def test_admin_question_delete_is_soft_and_excluded_from_selection(
        app, registered_client):
    from app.models import InterviewSession, Question, User

    with app.app_context():
        user = User.get_by_username('candidate')
        question = Question.query.filter(Question.is_active.is_(True)).first()
        question_id = question.id
        InterviewSession.create(user.id, 'java_backend', [question_id])

    _login_admin(registered_client)
    response = registered_client.delete(f'/api/admin/questions/{question_id}')
    assert response.status_code == 200
    assert '历史面试数据已保留' in response.get_json()['message']

    with app.app_context():
        question = db.session.get(Question, question_id)
        assert question is not None
        assert question.is_active is False
        assert question.deleted_at is not None
        session = InterviewSession.query.filter(
            InterviewSession.question_ids == json.dumps([question_id])
        ).one()
        assert question_id in session.get_question_ids()

        from app.services.question_service import select_questions
        selected = select_questions('java_backend', 10)
        assert question_id not in [item.id for item in selected]


def test_clear_questions_preserves_rows_as_inactive(app, registered_client):
    _login_admin(registered_client)
    response = registered_client.delete('/api/admin/questions/clear')
    assert response.status_code == 200
    assert response.get_json()['deleted'] == 5

    from app.models import Question
    with app.app_context():
        assert Question.query.count() == 5
        assert Question.query.filter(Question.is_active.is_(True)).count() == 0


def test_source_session_cannot_be_deleted_before_targeted_training(
        app, registered_client):
    from app.models import InterviewSession, Question, User

    with app.app_context():
        user = User.get_by_username('candidate')
        question_ids = [row.id for row in Question.query.limit(3).all()]
        source = InterviewSession.create(user.id, 'java_backend', question_ids)
        training = InterviewSession.create(
            user.id,
            'java_backend',
            question_ids,
            mode='training',
            source_session_id=source.id,
            training_task_id='task-integrity',
        )
        source_id = source.id
        training_id = training.id

    blocked = registered_client.delete(f'/api/interview/sessions/{source_id}')
    assert blocked.status_code == 409
    assert '专项训练引用' in blocked.get_json()['message']
    assert registered_client.delete(
        f'/api/interview/sessions/{training_id}'
    ).status_code == 200
    assert registered_client.delete(
        f'/api/interview/sessions/{source_id}'
    ).status_code == 200
