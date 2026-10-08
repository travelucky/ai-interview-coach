import json

from sqlalchemy import inspect, text

from app import db


SESSION_COLUMNS = {
    'completed_at': 'DATETIME',
    'current_question_index': 'INTEGER NOT NULL DEFAULT 0',
    'answered_question_count': 'INTEGER NOT NULL DEFAULT 0',
    'total_question_count': 'INTEGER NOT NULL DEFAULT 0',
    'failure_reason': 'TEXT',
    'scoring_version': "VARCHAR(32) NOT NULL DEFAULT 'mvp-v1'",
    'mode': "VARCHAR(32) NOT NULL DEFAULT 'standard'",
    'source_session_id': 'INTEGER',
    'training_task_id': 'VARCHAR(64)',
}

QUESTION_COLUMNS = {
    'topic': 'VARCHAR(128)',
    'scoring_points': 'TEXT',
    'is_active': 'BOOLEAN NOT NULL DEFAULT 1',
    'deleted_at': 'DATETIME',
    'source': 'VARCHAR(128)',
    'review_status': "VARCHAR(32) NOT NULL DEFAULT 'pending'",
    'reviewer': 'VARCHAR(128)',
    'reviewed_at': 'DATETIME',
    'content_version': 'INTEGER NOT NULL DEFAULT 1',
    'is_core': 'BOOLEAN NOT NULL DEFAULT 0',
}

KNOWLEDGE_COLUMNS = {
    'topic': 'VARCHAR(128)',
    'keywords': 'TEXT',
    'difficulty': 'INTEGER DEFAULT 1',
    'source': 'VARCHAR(128)',
    'document_name': 'VARCHAR(256)',
    'chunk_index': 'INTEGER',
    'source_hash': 'VARCHAR(64)',
    'content_hash': 'VARCHAR(64)',
    'embedding_model': 'VARCHAR(128)',
    'embedding_vector': 'TEXT',
    'embedding_updated_at': 'DATETIME',
}

REPORT_COLUMNS = {
    'scoring_source': "VARCHAR(32) NOT NULL DEFAULT 'rule'",
    'scoring_version': "VARCHAR(32) NOT NULL DEFAULT 'mvp-v1'",
    'training_tasks': 'TEXT',
}

MESSAGE_COLUMNS = {
    'client_request_id': 'VARCHAR(64)',
    'question_id': 'INTEGER',
    'message_kind': 'VARCHAR(32)',
    'answer_source': 'VARCHAR(16)',
    'raw_transcript': 'TEXT',
    'edited_at': 'DATETIME',
}

EXPRESSION_COLUMNS = {
    'acoustic_metrics': 'TEXT',
}

QUESTION_SCORE_COLUMNS = {
    'knowledge_references': 'TEXT',
    'dimension_scores': 'TEXT',
}


def ensure_mvp_schema():
    inspector = inspect(db.engine)
    if 'interview_session' not in inspector.get_table_names():
        return []

    existing_columns = {
        column['name'] for column in inspector.get_columns('interview_session')
    }
    applied = []
    message_columns = {
        column['name'] for column in inspector.get_columns('interview_message')
    } if 'interview_message' in inspector.get_table_names() else set()
    question_columns = {
        column['name'] for column in inspector.get_columns('question')
    } if 'question' in inspector.get_table_names() else set()
    knowledge_columns = {
        column['name'] for column in inspector.get_columns('knowledge')
    } if 'knowledge' in inspector.get_table_names() else set()
    report_columns = {
        column['name'] for column in inspector.get_columns('interview_report')
    } if 'interview_report' in inspector.get_table_names() else set()
    expression_columns = {
        column['name'] for column in inspector.get_columns('expression_metric')
    } if 'expression_metric' in inspector.get_table_names() else set()
    question_score_columns = {
        column['name'] for column in inspector.get_columns('question_score')
    } if 'question_score' in inspector.get_table_names() else set()

    from app.models.expression_metric import ExpressionMetric
    ExpressionMetric.__table__.create(bind=db.engine, checkfirst=True)
    from app.models.retrieval_event import RetrievalEvent
    RetrievalEvent.__table__.create(bind=db.engine, checkfirst=True)
    from app.models.training_task import TrainingTask
    TrainingTask.__table__.create(bind=db.engine, checkfirst=True)
    if not expression_columns:
        expression_columns = {
            column['name'] for column in inspect(db.engine).get_columns('expression_metric')
        }

    with db.engine.begin() as connection:
        for column_name, definition in SESSION_COLUMNS.items():
            if column_name in existing_columns:
                continue
            connection.execute(
                text(
                    f'ALTER TABLE interview_session '
                    f'ADD COLUMN {column_name} {definition}'
                )
            )
            applied.append(column_name)

        for column_name, definition in MESSAGE_COLUMNS.items():
            if not message_columns or column_name in message_columns:
                continue
            connection.execute(
                text(
                    f'ALTER TABLE interview_message '
                    f'ADD COLUMN {column_name} {definition}'
                )
            )
            applied.append(f'interview_message.{column_name}')
        if message_columns:
            connection.execute(
                text(
                    'CREATE UNIQUE INDEX IF NOT EXISTS '
                    'uq_interview_message_session_request '
                    'ON interview_message (session_id, client_request_id) '
                    'WHERE client_request_id IS NOT NULL'
                )
            )

        for column_name, definition in QUESTION_COLUMNS.items():
            if not question_columns or column_name in question_columns:
                continue
            connection.execute(
                text(f'ALTER TABLE question ADD COLUMN {column_name} {definition}')
            )
            applied.append(f'question.{column_name}')
        if question_columns:
            connection.execute(text(
                'CREATE INDEX IF NOT EXISTS ix_question_review_status '
                'ON question (review_status)'
            ))
            connection.execute(text(
                'CREATE INDEX IF NOT EXISTS ix_question_is_core '
                'ON question (is_core)'
            ))

        for column_name, definition in KNOWLEDGE_COLUMNS.items():
            if not knowledge_columns or column_name in knowledge_columns:
                continue
            connection.execute(
                text(f'ALTER TABLE knowledge ADD COLUMN {column_name} {definition}')
            )
            applied.append(f'knowledge.{column_name}')
        if knowledge_columns:
            connection.execute(text(
                'CREATE INDEX IF NOT EXISTS ix_knowledge_source_hash '
                'ON knowledge (source_hash)'
            ))
            connection.execute(text(
                'CREATE INDEX IF NOT EXISTS ix_knowledge_content_hash '
                'ON knowledge (content_hash)'
            ))

        for column_name, definition in REPORT_COLUMNS.items():
            if not report_columns or column_name in report_columns:
                continue
            connection.execute(
                text(f'ALTER TABLE interview_report ADD COLUMN {column_name} {definition}')
            )
            applied.append(f'interview_report.{column_name}')

        for column_name, definition in EXPRESSION_COLUMNS.items():
            if column_name in expression_columns:
                continue
            connection.execute(text(
                f'ALTER TABLE expression_metric ADD COLUMN {column_name} {definition}'
            ))
            applied.append(f'expression_metric.{column_name}')

        for column_name, definition in QUESTION_SCORE_COLUMNS.items():
            if not question_score_columns or column_name in question_score_columns:
                continue
            connection.execute(text(
                f'ALTER TABLE question_score ADD COLUMN {column_name} {definition}'
            ))
            applied.append(f'question_score.{column_name}')

        connection.execute(
            text(
                "UPDATE interview_session "
                "SET status = 'interviewing' "
                "WHERE status = 'in_progress'"
            )
        )
        sessions = connection.execute(
            text(
                'SELECT id, question_ids, total_question_count '
                'FROM interview_session'
            )
        ).mappings().all()
        for session in sessions:
            if session['total_question_count']:
                continue
            try:
                question_ids = json.loads(session['question_ids'] or '[]')
            except (TypeError, ValueError):
                question_ids = []
            total = len(question_ids) if isinstance(question_ids, list) else 0
            connection.execute(
                text(
                    'UPDATE interview_session '
                    'SET total_question_count = :total '
                    'WHERE id = :session_id'
                ),
                {'total': total, 'session_id': session['id']},
            )
    return applied
