from app import create_app, db
from app.models import InterviewReport, InterviewSession, Question, SystemConfig
from scripts.init_db import seed_knowledge, seed_positions, seed_questions


def test_java_and_web_seeded_text_interviews_complete_offline(tmp_path, monkeypatch):
    """Release smoke test: two MVP positions finish without any external API."""
    database_path = tmp_path / 'e2e.db'
    application = create_app(
        'testing',
        {
            'SECRET_KEY': 'e2e-test-key',
            'SECRET_KEY_IS_EPHEMERAL': False,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database_path}',
            'LLM_API_KEY': '',
            'XFYUN_APP_ID': '',
            'XFYUN_API_KEY': '',
            'XFYUN_API_SECRET': '',
            'EMBEDDING_API_KEY': '',
            'EMBEDDING_BASE_URL': '',
            'EMBEDDING_MODEL': '',
        },
    )
    with application.app_context():
        db.create_all()
        SystemConfig.seed_defaults()
        seed_positions()
        seed_questions()
        seed_knowledge()

    monkeypatch.setattr(
        'app.services.followup_service.decide_followup_or_next',
        lambda *args, **_kwargs: ('next', args[3]),
    )
    client = application.test_client()
    registered = client.post(
        '/api/auth/register',
        json={
            'username': 'e2e_candidate',
            'password': 'Candidate123!',
            'confirm_password': 'Candidate123!',
        },
    )
    assert registered.status_code == 201
    assert client.post(
        '/api/auth/login',
        json={'username': 'e2e_candidate', 'password': 'Candidate123!'},
    ).status_code == 200

    completed_ids = []
    for position_code in ('java_backend', 'web_frontend'):
        started = client.post(
            '/api/interview/start', json={'position_code': position_code}
        )
        assert started.status_code == 200
        start_payload = started.get_json()
        session_id = start_payload['session_id']
        question_ids = start_payload['question_ids']
        assert len(question_ids) == 5
        with application.app_context():
            assert {Question.get_by_id(item).type for item in question_ids} == {
                'technical', 'project', 'scenario', 'behavioral'
            }

        for answer_index in range(5):
            answered = client.post(
                f'/api/interview/{session_id}/reply',
                json={
                    'content': (
                        '我会先说明核心原理，再结合项目实践给出验证、监控、'
                        '异常处理和复盘方案。'
                    ),
                    'request_id': f'{position_code}-{answer_index}',
                },
            )
            assert answered.status_code == 200
        finished = client.post(f'/api/interview/{session_id}/finish')
        assert finished.status_code == 200
        report = client.get(f'/api/interview/sessions/{session_id}/report')
        assert report.status_code == 200
        report_payload = report.get_json()['report']
        assert report_payload['scoring_source'] == 'rule'
        assert report_payload['scoring_version'] == 'mvp-v3'
        assert len(report_payload['question_scores']) == 5
        completed_ids.append(session_id)

    dashboard = client.get('/api/dashboard/user')
    assert dashboard.status_code == 200
    assert dashboard.get_json()['standard_total_sessions'] == 2
    with application.app_context():
        for session_id in completed_ids:
            assert InterviewSession.get_by_id(session_id).status == 'completed'
            assert InterviewReport.get_by_session_id(session_id) is not None

    with application.app_context():
        db.session.remove()
        db.drop_all()
