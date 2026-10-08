import json
from datetime import datetime, timedelta


def test_user_dashboard_separates_training_and_uses_latest_five_comparable_scores(
        app, registered_client):
    from app import db
    from app.models import InterviewReport, InterviewSession, Question, User

    with app.app_context():
        user = User.get_by_username('candidate')
        question_id = Question.query.first().id
        base_time = datetime(2026, 1, 1)
        for index, score in enumerate((10, 20, 30, 40, 50, 60)):
            session = InterviewSession.create(
                user.id,
                'java_backend',
                [question_id],
            )
            session.started_at = base_time + timedelta(days=index)
            session.scoring_version = 'mvp-v2'
            InterviewReport.create(
                session_id=session.id,
                overall_score=score,
                scoring_source='rule',
                scoring_version='mvp-v2',
            )

        training = InterviewSession.create(
            user.id,
            'java_backend',
            [question_id],
            mode='training',
        )
        training.started_at = base_time + timedelta(days=10)
        InterviewReport.create(
            session_id=training.id,
            overall_score=99,
            scoring_source='rule',
            scoring_version='mvp-v2',
        )
        db.session.commit()

    response = registered_client.get('/api/dashboard/user')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['total_sessions'] == 7
    assert payload['standard_total_sessions'] == 6
    assert payload['training_total_sessions'] == 1
    assert payload['training_completed_sessions'] == 1
    assert payload['average_score'] == 35
    assert payload['best_score'] == 60
    assert payload['recent_5_avg'] == 40
    assert [item['score'] for item in payload['average_score_trend']] == [
        10, 20, 30, 40, 50, 60,
    ]
    assert payload['trend_position_code'] == 'java_backend'
    assert all('（专项）' not in item['position'] for item in payload['recent_scores'])
    assert isinstance(payload['dimension_trend'], list)
    assert isinstance(payload['question_type_trend'], list)
    assert isinstance(payload['high_frequency_weaknesses'], list)
    assert isinstance(payload['improved_weaknesses'], list)
    assert isinstance(payload['training_comparisons'], list)
    assert payload['trend_uses_fallback'] is False
    assert payload['available_training_tasks'] == 0


def test_user_dashboard_uses_comparable_history_and_legacy_dimensions(
        app, registered_client):
    from app import db
    from app.models import InterviewReport, InterviewSession, Question, User

    with app.app_context():
        user = User.get_by_username('candidate')
        question_id = Question.query.first().id
        base_time = datetime(2026, 2, 1)
        for index, score in enumerate((50, 60, 70)):
            session = InterviewSession.create(
                user.id,
                'web_sec',
                [question_id],
            )
            session.started_at = base_time + timedelta(days=index)
            session.scoring_version = 'mvp-v2'
            InterviewReport.create(
                session_id=session.id,
                overall_score=score,
                scoring_source='rule',
                scoring_version='mvp-v2',
                content_analysis=json.dumps({
                    'technical_correctness': score,
                    'knowledge_depth': score - 1,
                    'logic': score - 2,
                    'job_fit': score - 3,
                    'question_type_scores': {
                        'technical': score,
                        'scenario': score - 5,
                    },
                }),
            )

        latest = InterviewSession.create(
            user.id,
            'java_backend',
            [question_id],
        )
        latest.started_at = base_time + timedelta(days=10)
        latest.scoring_version = 'mvp-v2'
        InterviewReport.create(
            session_id=latest.id,
            overall_score=80,
            scoring_source='rule',
            scoring_version='mvp-v2',
            content_analysis='{}',
            training_tasks=json.dumps([
                {'id': 'legacy-1', 'status': 'todo'},
                {'id': 'legacy-2', 'status': 'todo'},
            ]),
        )
        db.session.commit()

    response = registered_client.get('/api/dashboard/user')
    assert response.status_code == 200
    payload = response.get_json()

    assert payload['trend_position_code'] == 'web_sec'
    assert payload['trend_scoring_version'] == 'mvp-v2'
    assert payload['trend_uses_fallback'] is True
    assert [item['score'] for item in payload['average_score_trend']] == [
        50, 60, 70,
    ]
    assert [item['scores']['logic_structure'] for item in payload['dimension_trend']] == [
        48, 58, 68,
    ]
    assert [item['scores']['technical'] for item in payload['question_type_trend']] == [
        50, 60, 70,
    ]
    assert payload['available_training_tasks'] == 2


def test_user_dashboard_derives_weakness_change_from_low_dimensions(
        app, registered_client):
    from app import db
    from app.models import InterviewReport, InterviewSession, Question, User

    with app.app_context():
        user = User.get_by_username('candidate')
        question_id = Question.query.first().id
        base_time = datetime(2026, 3, 1)
        for index, score in enumerate((45, 65, 85, 90)):
            session = InterviewSession.create(
                user.id,
                'java_backend',
                [question_id],
            )
            session.started_at = base_time + timedelta(days=index)
            session.scoring_version = 'mvp-v3'
            InterviewReport.create(
                session_id=session.id,
                overall_score=score,
                scoring_source='rule',
                scoring_version='mvp-v3',
                content_analysis=json.dumps({
                    'dimensions': {
                        key: {
                            'status': 'evaluated',
                            'score': score,
                        }
                        for key in (
                            'technical_correctness',
                            'knowledge_depth',
                            'logic_structure',
                            'project_practice',
                            'job_fit',
                        )
                    },
                }),
            )
        db.session.commit()

    payload = registered_client.get('/api/dashboard/user').get_json()

    frequent = {
        item['label']: item['count']
        for item in payload['high_frequency_weaknesses']
    }
    improved = {
        item['label']: (item['earlier_count'], item['recent_count'])
        for item in payload['improved_weaknesses']
    }
    assert frequent['能力维度：技术正确性'] == 2
    assert frequent['能力维度：逻辑结构'] == 2
    assert improved['能力维度：技术正确性'] == (2, 0)
    assert improved['能力维度：逻辑结构'] == (2, 0)
