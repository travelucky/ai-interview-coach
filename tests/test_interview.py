def test_authenticated_user_can_list_positions_and_start_interview(registered_client):
    position_response = registered_client.get('/api/user/positions')
    assert position_response.status_code == 200
    positions = position_response.get_json()['positions']
    assert positions[0]['code'] == 'java_backend'
    assert positions[0]['maturity'] == 'mvp'

    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    assert start_response.status_code == 200
    payload = start_response.get_json()
    assert payload['success'] is True
    assert payload['session_id'] > 0
    assert payload['first_question']['content']
    assert len(payload['question_ids']) == 5
    assert payload['progress'] == {'current': 1, 'answered': 0, 'total': 5}


def test_session_state_restores_progress_and_history_without_duplicates(
        app, registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    reply_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json={
            'content': '刷新恢复测试回答，说明核心原理。',
            'request_id': 'resume-state-001',
        },
    )
    assert reply_response.status_code == 200

    first_state = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    )
    repeated_state = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    )
    assert first_state.status_code == 200
    assert repeated_state.status_code == 200
    first_payload = first_state.get_json()
    repeated_payload = repeated_state.get_json()
    assert first_payload['session']['status'] == 'interviewing'
    assert first_payload['progress']['answered'] == 1
    assert first_payload['current_question']['content']
    assert first_payload['messages'] == repeated_payload['messages']
    assert first_payload['available_actions']['can_reply'] is True

    from app.models import InterviewMessage
    with app.app_context():
        assert InterviewMessage.query.filter_by(session_id=session_id).count() == 3


def test_session_can_be_restored_after_logout_and_login(registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    registered_client.post('/api/auth/logout')
    login_response = registered_client.post(
        '/api/auth/login',
        json={'username': 'candidate', 'password': 'Candidate123!'},
    )
    assert login_response.status_code == 200

    state_response = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    )
    active_response = registered_client.get('/api/interview/sessions/active')
    assert state_response.status_code == 200
    assert state_response.get_json()['session_id'] == session_id
    assert active_response.status_code == 200
    assert session_id in [
        item['id'] for item in active_response.get_json()['sessions']
    ]


def test_last_question_enters_scoring_and_can_auto_finish(
        app, registered_client, monkeypatch):
    def always_advance(*args, **_kwargs):
        return 'next', args[3]

    monkeypatch.setattr(
        'app.services.followup_service.decide_followup_or_next',
        always_advance,
    )
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    final_payload = None
    for answer_number in range(5):
        response = registered_client.post(
            f'/api/interview/{session_id}/reply',
            json={
                'content': f'第 {answer_number + 1} 题回答，说明核心原理。',
                'request_id': f'auto-finish-{answer_number}',
            },
        )
        assert response.status_code == 200
        final_payload = response.get_json()

    assert final_payload['status'] == 'scoring'
    assert final_payload['auto_finish'] is True
    assert final_payload['available_actions']['can_reply'] is False
    repeated_final_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json={
            'content': '该内容不会重复保存。',
            'request_id': 'auto-finish-4',
        },
    )
    assert repeated_final_response.status_code == 200
    assert repeated_final_response.get_json()['duplicate'] is True
    assert repeated_final_response.get_json()['status'] == 'scoring'
    state_response = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    )
    assert state_response.get_json()['session']['status'] == 'scoring'

    finish_response = registered_client.post(f'/api/interview/{session_id}/finish')
    assert finish_response.status_code == 200
    with app.app_context():
        from app.models import InterviewSession
        assert InterviewSession.get_by_id(session_id).status == 'completed'


def test_user_can_abandon_active_session_and_history_is_kept(
        app, registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    abandon_response = registered_client.post(
        f'/api/interview/sessions/{session_id}/abandon'
    )
    assert abandon_response.status_code == 200
    payload = abandon_response.get_json()
    assert payload['session']['status'] == 'abandoned'
    assert payload['session']['failure_reason'] == 'user_abandoned'
    assert payload['session']['ended_at']
    assert payload['available_actions']['can_reply'] is False

    active_response = registered_client.get('/api/interview/sessions/active')
    assert session_id not in [
        item['id'] for item in active_response.get_json()['sessions']
    ]
    history_response = registered_client.get('/api/interview/sessions')
    history_item = next(
        item for item in history_response.get_json()['sessions']
        if item['id'] == session_id
    )
    assert history_item['status'] == 'abandoned'

    with app.app_context():
        from app.models import InterviewMessage
        assert InterviewMessage.query.filter_by(session_id=session_id).count() == 1


def test_start_interview_requires_login(client):
    response = client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    assert response.status_code == 401


def test_user_cannot_access_another_users_session(registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    registered_client.post('/api/auth/logout')
    registered_client.post(
        '/api/auth/register',
        json={
            'username': 'intruder',
            'password': 'Intruder123!',
            'confirm_password': 'Intruder123!',
        },
    )
    registered_client.post(
        '/api/auth/login',
        json={'username': 'intruder', 'password': 'Intruder123!'},
    )

    reply_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json={'content': '不应被保存的回答。'},
    )
    finish_response = registered_client.post(f'/api/interview/{session_id}/finish')
    report_response = registered_client.get(
        f'/api/interview/sessions/{session_id}/report'
    )
    state_response = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    )
    abandon_response = registered_client.post(
        f'/api/interview/sessions/{session_id}/abandon'
    )

    assert reply_response.status_code == 404
    assert finish_response.status_code == 404
    assert report_response.status_code == 404
    assert state_response.status_code == 404
    assert abandon_response.status_code == 404


def test_reply_request_id_is_idempotent(app, registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    payload = {
        'content': '这是一条带幂等标识的回答。',
        'request_id': 'fixed-request-id-001',
    }

    first_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json=payload,
    )
    repeated_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json=payload,
    )

    assert first_response.status_code == 200
    assert repeated_response.status_code == 200
    assert repeated_response.get_json()['duplicate'] is True
    assert repeated_response.get_json()['content'] == first_response.get_json()['content']

    from app.models import InterviewMessage
    with app.app_context():
        assert InterviewMessage.query.filter_by(session_id=session_id).count() == 3


def test_only_latest_answer_under_followup_can_be_edited_consistently(
        app, registered_client, monkeypatch):
    def decide(_question, answer, _followups, next_question, *_args, **_kwargs):
        if '补充完整' in answer:
            return 'next', next_question
        return 'follow_up', '请补充说明你的具体实践。'

    monkeypatch.setattr(
        'app.services.followup_service.decide_followup_or_next',
        decide,
    )
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    reply_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json={'content': '第一次回答。', 'request_id': 'editable-answer-001'},
    )
    assert reply_response.status_code == 200
    reply_payload = reply_response.get_json()
    assert reply_payload['user_message_editable'] is True
    message_id = reply_payload['user_message_id']

    state_before = registered_client.get(
        f'/api/interview/sessions/{session_id}/state'
    ).get_json()
    answer_before = next(
        item for item in state_before['messages'] if item['id'] == message_id
    )
    assert answer_before['editable'] is True

    update_response = registered_client.patch(
        f'/api/interview/{session_id}/messages/{message_id}',
        json={'content': '补充完整：说明核心原理与具体实践。'},
    )
    assert update_response.status_code == 200
    updated = update_response.get_json()
    assert updated['assistant_message_kind'] == 'question'
    assert updated['editable'] is False
    assert updated['progress']['answered'] == 1

    repeated_update = registered_client.patch(
        f'/api/interview/{session_id}/messages/{message_id}',
        json={'content': '进入下一题后不应允许再次修改。'},
    )
    assert repeated_update.status_code == 409

    from app.models import InterviewMessage, InterviewSession
    with app.app_context():
        messages = InterviewMessage.list_by_session(session_id)
        assert len(messages) == 3
        assert messages[1].content == '补充完整：说明核心原理与具体实践。'
        assert messages[1].edited_at is not None
        assert messages[2].message_kind == 'question'
        session = InterviewSession.get_by_id(session_id)
        assert session.current_question_index == 1
        assert session.answered_question_count == 1


def test_answer_edit_generation_failure_preserves_original_data(
        app, registered_client, monkeypatch):
    monkeypatch.setattr(
        'app.services.followup_service.decide_followup_or_next',
        lambda *_args, **_kwargs: ('follow_up', '原追问内容'),
    )
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    reply_payload = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json={'content': '原回答内容。'},
    ).get_json()
    message_id = reply_payload['user_message_id']

    def fail_regeneration(*_args, **_kwargs):
        raise RuntimeError('simulated edit regeneration failure')

    monkeypatch.setattr(
        'app.services.followup_service.decide_followup_or_next',
        fail_regeneration,
    )
    update_response = registered_client.patch(
        f'/api/interview/{session_id}/messages/{message_id}',
        json={'content': '不应写入的新回答。'},
    )
    assert update_response.status_code == 503

    from app.models import InterviewMessage
    with app.app_context():
        messages = InterviewMessage.list_by_session(session_id)
        assert messages[1].content == '原回答内容。'
        assert messages[1].edited_at is None
        assert messages[2].content == '原追问内容'


def test_reply_failure_does_not_leave_stuck_answer_and_retry_succeeds(
        app, registered_client, monkeypatch):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    payload = {
        'content': '事务失败后仍然需要能够安全重试的回答。',
        'request_id': 'reply-transaction-failure-001',
    }

    def fail_followup(*_args, **_kwargs):
        raise RuntimeError('simulated follow-up failure')

    monkeypatch.setattr(
        'app.services.followup_service.decide_followup_or_next',
        fail_followup,
    )
    failed_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json=payload,
    )
    assert failed_response.status_code == 503

    from app.models import InterviewMessage
    with app.app_context():
        assert InterviewMessage.get_by_client_request_id(
            session_id,
            payload['request_id'],
        ) is None

    monkeypatch.undo()
    retry_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json=payload,
    )
    assert retry_response.status_code == 200

    with app.app_context():
        assert InterviewMessage.query.filter_by(
            session_id=session_id,
            client_request_id=payload['request_id'],
        ).count() == 1


def test_reply_recovers_legacy_partial_answer(app, registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    question_id = start_response.get_json()['question_ids'][0]
    request_id = 'legacy-partial-answer-001'

    from app.models import InterviewMessage
    from app.models.interview_message import MessageKind, MessageRole
    with app.app_context():
        partial = InterviewMessage.create(
            session_id,
            MessageRole.USER,
            '已经保存但还没有生成追问的历史回答。',
            InterviewMessage.get_next_sequence(session_id),
            client_request_id=request_id,
            question_id=question_id,
            message_kind=MessageKind.ANSWER,
        )
        partial_message_id = partial.id

    recovered_response = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json={
            'content': '客户端重试时携带的内容不应重复写入。',
            'request_id': request_id,
        },
    )
    assert recovered_response.status_code == 200
    assert recovered_response.get_json()['duplicate'] is True
    assert recovered_response.get_json()['recovered'] is True
    assert recovered_response.get_json()['user_message_id'] == partial_message_id

    with app.app_context():
        messages = InterviewMessage.list_by_session(session_id)
        assert len(messages) == 3
        assert len([item for item in messages if item.role == MessageRole.USER]) == 1


def test_cannot_finish_before_minimum_question_count(registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']

    finish_response = registered_client.post(f'/api/interview/{session_id}/finish')

    assert finish_response.status_code == 409
    assert '至少完成 3 道正式题' in finish_response.get_json()['message']


def test_finish_after_minimum_answers_is_idempotent(app, registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']

    for answer_number in range(3):
        reply_response = registered_client.post(
            f'/api/interview/{session_id}/reply',
            json={'content': f'这是第 {answer_number + 1} 道题的完整回答，并说明核心原理。'},
        )
        assert reply_response.status_code == 200

    finish_response = registered_client.post(f'/api/interview/{session_id}/finish')
    assert finish_response.status_code == 200
    report_id = finish_response.get_json()['report_id']

    repeated_finish = registered_client.post(f'/api/interview/{session_id}/finish')
    assert repeated_finish.status_code == 200
    assert repeated_finish.get_json()['report_id'] == report_id

    report_response = registered_client.get(
        f'/api/interview/sessions/{session_id}/report'
    )
    assert report_response.status_code == 200
    report = report_response.get_json()['report']
    assert report['scoring_source'] == 'rule'
    assert report['scoring_version'] == 'mvp-v3'
    assert report['completion_ratio'] == 0.6
    assert report['created_at']
    assert report['session_mode'] == 'standard'
    assert report['content_analysis']['question_type_scores']
    assert len(report['question_scores']) == 3
    assert report['retrieval_trace']
    assert all(
        event['retrieval_version'] == 'hybrid-v2'
        for event in report['retrieval_trace']
    )
    assert report['retrieval_summary']
    assert sum(
        item['event_count'] for item in report['retrieval_summary']
    ) == len(report['retrieval_trace'])
    assert all(
        item['event_count'] == item['hit_count'] + item['rejected_count']
        for item in report['retrieval_summary']
    )
    assert 3 <= len(report['training_tasks']) <= 5
    for task in report['training_tasks']:
        assert task['title']
        assert task['objective']
        assert task['reason']
        assert task['answer_framework']
        assert task['status'] == 'todo'
    for question_score in report['question_scores']:
        assert 0 <= question_score['final_score'] <= 100
        assert question_score['question_content']
        assert question_score['scoring_source'] == 'rule'
        assert isinstance(question_score['covered_points'], list)
        assert isinstance(question_score['missing_points'], list)
        assert isinstance(question_score['evidence'], list)
        assert isinstance(question_score['knowledge_references'], list)
        assert set(question_score['dimension_scores']) == {
            'technical_correctness', 'knowledge_depth', 'logic_structure',
            'project_practice', 'job_fit', 'expression_performance',
        }

    from app.models import QuestionScore
    with app.app_context():
        assert QuestionScore.query.filter_by(session_id=session_id).count() == 3


def test_user_can_start_targeted_training_from_owned_report(
        app, registered_client, monkeypatch):
    monkeypatch.setattr(
        'app.services.followup_service.decide_followup_or_next',
        lambda *_args, **_kwargs: ('next', _args[3]),
    )
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    source_session_id = start_response.get_json()['session_id']
    for answer_number in range(3):
        response = registered_client.post(
            f'/api/interview/{source_session_id}/reply',
            json={'content': f'回答 {answer_number + 1} 说明核心原理和实际案例。'},
        )
        assert response.status_code == 200
    assert registered_client.post(
        f'/api/interview/{source_session_id}/finish'
    ).status_code == 200
    report = registered_client.get(
        f'/api/interview/sessions/{source_session_id}/report'
    ).get_json()['report']
    task = report['training_tasks'][0]

    invalid_response = registered_client.post(
        '/api/interview/training/start',
        json={'source_session_id': source_session_id, 'task_id': 'tampered-task'},
    )
    assert invalid_response.status_code == 404

    training_response = registered_client.post(
        '/api/interview/training/start',
        json={'source_session_id': source_session_id, 'task_id': task['id']},
    )
    assert training_response.status_code == 200
    payload = training_response.get_json()
    assert payload['mode'] == 'training'
    assert payload['source_session_id'] == source_session_id
    assert payload['training_task_id'] == task['id']
    assert payload['training_task']['title'] == task['title']
    assert len(payload['question_ids']) == 3
    assert payload['question_ids'][0] == task['practice_question']['question_id']

    from app.models import InterviewSession, Question
    with app.app_context():
        session = InterviewSession.get_by_id(payload['session_id'])
        assert session.mode == 'training'
        assert session.source_session_id == source_session_id
        assert session.training_task_id == task['id']
        questions = [Question.get_by_id(question_id) for question_id in payload['question_ids']]
        assert all(question.position.code == 'java_backend' for question in questions)

    source_report = registered_client.get(
        f'/api/interview/sessions/{source_session_id}/report'
    ).get_json()['report']
    started_task = next(item for item in source_report['training_tasks'] if item['id'] == task['id'])
    assert started_task['status'] == 'in_progress'
    assert started_task['training_session_id'] == payload['session_id']

    for answer_number in range(2):
        response = registered_client.post(
            f"/api/interview/{payload['session_id']}/reply",
            json={'content': f'专项回答 {answer_number + 1} 说明核心原理、边界和验证。'},
        )
        assert response.status_code == 200
    assert registered_client.post(
        f"/api/interview/{payload['session_id']}/finish"
    ).status_code == 200
    training_report = registered_client.get(
        f"/api/interview/sessions/{payload['session_id']}/report"
    ).get_json()['report']
    assert training_report['training_comparison']['comparable'] is True
    assert training_report['training_comparison']['scoring_version'] == 'mvp-v3'

    source_report = registered_client.get(
        f'/api/interview/sessions/{source_session_id}/report'
    ).get_json()['report']
    completed_task = next(item for item in source_report['training_tasks'] if item['id'] == task['id'])
    assert completed_task['status'] == 'completed'
    assert completed_task['comparison']['comparable'] is True


def test_user_cannot_start_training_from_another_users_report(registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    source_session_id = start_response.get_json()['session_id']
    for answer_number in range(3):
        registered_client.post(
            f'/api/interview/{source_session_id}/reply',
            json={'content': f'回答 {answer_number + 1} 说明核心原理。'},
        )
    registered_client.post(f'/api/interview/{source_session_id}/finish')
    report = registered_client.get(
        f'/api/interview/sessions/{source_session_id}/report'
    ).get_json()['report']
    task_id = report['training_tasks'][0]['id']

    registered_client.post('/api/auth/logout')
    registered_client.post(
        '/api/auth/register',
        json={
            'username': 'training_intruder',
            'password': 'Intruder123!',
            'confirm_password': 'Intruder123!',
        },
    )
    registered_client.post(
        '/api/auth/login',
        json={'username': 'training_intruder', 'password': 'Intruder123!'},
    )
    response = registered_client.post(
        '/api/interview/training/start',
        json={'source_session_id': source_session_id, 'task_id': task_id},
    )
    assert response.status_code == 404


def test_scoring_failure_keeps_answers_and_allows_retry(registered_client, monkeypatch):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    for answer_number in range(3):
        response = registered_client.post(
            f'/api/interview/{session_id}/reply',
            json={'content': f'用于失败恢复测试的回答 {answer_number + 1}，包括核心原理。'},
        )
        assert response.status_code == 200

    def fail_scoring(_session_id):
        raise RuntimeError('simulated scoring error')

    monkeypatch.setattr('app.services.scoring_service.score_interview', fail_scoring)
    failed_finish = registered_client.post(f'/api/interview/{session_id}/finish')
    assert failed_finish.status_code == 503

    sessions_response = registered_client.get('/api/interview/sessions')
    session = next(
        item for item in sessions_response.get_json()['sessions']
        if item['id'] == session_id
    )
    assert session['status'] == 'failed'
    assert session['answered_question_count'] == 3

    monkeypatch.undo()
    retry_response = registered_client.post(f'/api/interview/{session_id}/finish')
    assert retry_response.status_code == 200


def test_finish_rolls_back_scores_and_report_when_completion_fails(
        app, registered_client, monkeypatch):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    for answer_number in range(3):
        response = registered_client.post(
            f'/api/interview/{session_id}/reply',
            json={'content': f'事务回滚测试回答 {answer_number + 1}，说明核心原理。'},
        )
        assert response.status_code == 200

    from app.models import InterviewReport, InterviewSession, QuestionScore
    from app.models.interview_session import SessionStatus
    original_transition = InterviewSession.transition_to

    def fail_completed_transition(self, status, *args, **kwargs):
        if status == SessionStatus.COMPLETED:
            raise RuntimeError('simulated completion transition failure')
        return original_transition(self, status, *args, **kwargs)

    monkeypatch.setattr(
        InterviewSession,
        'transition_to',
        fail_completed_transition,
    )
    failed_finish = registered_client.post(f'/api/interview/{session_id}/finish')
    assert failed_finish.status_code == 503

    with app.app_context():
        assert InterviewReport.get_by_session_id(session_id) is None
        assert QuestionScore.query.filter_by(session_id=session_id).count() == 0
        assert InterviewSession.get_by_id(session_id).status == SessionStatus.FAILED

    monkeypatch.undo()
    retry_finish = registered_client.post(f'/api/interview/{session_id}/finish')
    assert retry_finish.status_code == 200

    with app.app_context():
        assert InterviewReport.get_by_session_id(session_id) is not None
        assert QuestionScore.query.filter_by(session_id=session_id).count() == 3
        assert InterviewSession.get_by_id(session_id).status == SessionStatus.COMPLETED


def test_finish_recovers_session_stuck_in_scoring(app, registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']
    for answer_number in range(3):
        response = registered_client.post(
            f'/api/interview/{session_id}/reply',
            json={'content': f'评分状态恢复回答 {answer_number + 1}，说明核心原理。'},
        )
        assert response.status_code == 200

    from app.models import InterviewSession
    from app.models.interview_session import SessionStatus
    with app.app_context():
        session = InterviewSession.get_by_id(session_id)
        session.transition_to(SessionStatus.SCORING)

    finish_response = registered_client.post(f'/api/interview/{session_id}/finish')
    assert finish_response.status_code == 200

    with app.app_context():
        assert InterviewSession.get_by_id(session_id).status == SessionStatus.COMPLETED


def test_finish_reconciles_legacy_report_with_failed_session(app, registered_client):
    start_response = registered_client.post(
        '/api/interview/start',
        json={'position_code': 'java_backend'},
    )
    session_id = start_response.get_json()['session_id']

    from app.models import InterviewReport, InterviewSession
    from app.models.interview_session import SessionStatus
    with app.app_context():
        session = InterviewSession.get_by_id(session_id)
        session.transition_to(SessionStatus.SCORING)
        session.transition_to(SessionStatus.FAILED, failure_reason='legacy_split_state')
        report = InterviewReport.create(
            session_id=session_id,
            overall_score=60,
            scoring_source='rule',
            scoring_version='mvp-v2',
        )
        report_id = report.id

    finish_response = registered_client.post(f'/api/interview/{session_id}/finish')
    assert finish_response.status_code == 200
    assert finish_response.get_json()['report_id'] == report_id

    with app.app_context():
        session = InterviewSession.get_by_id(session_id)
        assert session.status == SessionStatus.COMPLETED
        assert session.failure_reason is None


def test_last_security_question_can_follow_up_and_score_from_reference(app, registered_client):
    from app import db
    from app.models import InterviewMessage, InterviewSession, Position, Question, User
    from app.models.interview_message import MessageKind, MessageRole
    from app.models.question import QuestionType

    with app.app_context():
        user = User.get_by_username('candidate')
        position = Position(
            code='web_sec',
            name='网络安全',
            description='测试安全岗位',
        )
        db.session.add(position)
        db.session.flush()
        question = Question(
            position_id=position.id,
            type=QuestionType.SCENARIO,
            content='如何保护用户密码安全？',
            reference_answer='使用密码哈希和独立盐值保存密码',
            scoring_points='[]',
        )
        db.session.add(question)
        db.session.commit()
        session = InterviewSession.create(user.id, position.code, [question.id])
        InterviewMessage.create(
            session.id,
            MessageRole.ASSISTANT,
            question.content,
            1,
            question_id=question.id,
            message_kind=MessageKind.QUESTION,
        )
        session_id = session.id

    detailed_answer = (
        '系统使用密码哈希算法和每个用户独立的随机盐值保存密码，绝不保存明文或可逆密文。'
        '登录侧增加限速、多因素认证和异常告警，并制定泄露后的凭据轮换与审计流程。'
    ) * 2
    first_reply = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json={'content': detailed_answer},
    )
    assert first_reply.status_code == 200
    assert first_reply.get_json()['is_next_question'] is False
    assert '取舍' in first_reply.get_json()['content']

    second_reply = registered_client.post(
        f'/api/interview/{session_id}/reply',
        json={'content': '资源受限时优先保障哈希存储和登录限速，并保留强制重置密码的应急方案。'},
    )
    assert second_reply.status_code == 200
    assert second_reply.get_json()['progress']['answered'] == 1

    finish_response = registered_client.post(f'/api/interview/{session_id}/finish')
    assert finish_response.status_code == 200
    report = registered_client.get(
        f'/api/interview/sessions/{session_id}/report'
    ).get_json()['report']
    assert report['question_scores'][0]['final_score'] > 20
