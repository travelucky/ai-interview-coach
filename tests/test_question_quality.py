import json
from pathlib import Path

from app import db
from app.models import Position, Question
from app.services.question_quality_service import (
    is_question_interview_ready,
    question_quality_errors,
)
from app.services.question_service import select_questions


ROOT = Path(__file__).resolve().parent.parent


def _seed_questions():
    items = []
    for name in ('questions.json', 'questions_curated.json'):
        items.extend(json.loads((ROOT / 'seed' / name).read_text(encoding='utf-8')))
    return items


def test_every_versioned_question_passes_formal_quality_gate():
    questions = _seed_questions()
    assert len(questions) == 412
    failures = []
    for item in questions:
        errors = question_quality_errors(
            item.get('content'),
            item.get('reference_answer'),
            item.get('scoring_points'),
            item.get('type'),
        )
        if errors:
            failures.append({
                'position': item.get('position_code'),
                'content': item.get('content'),
                'errors': errors,
            })
    assert failures == []


def test_python_title_fragment_was_replaced_by_complete_prompt():
    questions = _seed_questions()
    assert not any(item.get('content') == '反转字符串' for item in questions)
    repaired = [
        item for item in questions
        if item.get('legacy_content') == '反转字符串'
    ]
    assert len(repaired) == 1
    assert repaired[0]['content'].startswith('请使用 Python 解决“反转字符串”问题')
    assert repaired[0]['content'].endswith('。')
    assert len(repaired[0]['scoring_points']) == 3


def test_unreviewed_fragment_can_never_be_selected(app):
    with app.app_context():
        position = Position.get_by_code('java_backend')
        bad = Question(
            position_id=position.id,
            type='technical',
            content='反转字符串',
            reference_answer='使用切片。',
            difficulty=1,
            scoring_points='[]',
            review_status='pending',
            is_core=True,
        )
        db.session.add(bad)
        db.session.commit()

        assert is_question_interview_ready(bad) is False
        for _ in range(20):
            assert bad.id not in {
                question.id for question in select_questions('java_backend', 5)
            }


def test_admin_cannot_approve_an_incomplete_question(client):
    login = client.post('/api/auth/login', json={
        'username': 'admin',
        'password': 'AdminPass123!',
    })
    assert login.status_code == 200
    position_id = client.get('/api/admin/positions').get_json()['positions'][0]['id']
    response = client.post('/api/admin/questions', json={
        'position_id': position_id,
        'type': 'technical',
        'content': '反转字符串',
        'reference_answer': '使用切片。',
        'scoring_points': [],
        'review_status': 'ai_reviewed',
        'reviewer': 'automatic-review',
    })
    assert response.status_code == 400
    assert '质量要求' in response.get_json()['message']


def test_all_user_positions_are_formal_mvp_options(registered_client):
    response = registered_client.get('/api/user/positions')
    assert response.status_code == 200
    positions = response.get_json()['positions']
    assert positions
    assert {item['maturity'] for item in positions} == {'mvp'}
