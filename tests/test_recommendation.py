from types import SimpleNamespace

from app.models import Question
from app.services.recommendation_service import (
    aggregate_weaknesses,
    build_training_tasks,
)


def test_similar_missing_points_are_merged():
    weaknesses = aggregate_weaknesses([
        {
            'question_id': 1,
            'question_type': 'technical',
            'question_content': '问题一',
            'final_score': 45,
            'missing_points': ['说明依赖注入核心原理'],
        },
        {
            'question_id': 2,
            'question_type': 'technical',
            'question_content': '问题二',
            'final_score': 55,
            'missing_points': ['依赖注入核心原理'],
        },
    ])

    assert len(weaknesses) == 1
    assert weaknesses[0]['occurrence_count'] == 2
    assert weaknesses[0]['question_ids'] == [1, 2]
    assert weaknesses[0]['lowest_score'] == 45


def test_training_tasks_are_actionable_and_position_scoped(app):
    with app.app_context():
        question = Question.query.filter_by(content='请解释依赖注入。').first()
        results = [{
            'question_id': question.id,
            'question_type': question.type,
            'question_content': question.content,
            'final_score': 40,
            'missing_points': ['说明依赖注入核心原理'],
        }]
        tasks = build_training_tasks(
            SimpleNamespace(position_code='java_backend'),
            results,
            expression_analysis={'status': 'not_measured'},
            limit=5,
        )

    assert 3 <= len(tasks) <= 5
    primary = tasks[0]
    assert primary['category'] == 'technical_knowledge'
    assert primary['objective']
    assert primary['reason']
    assert primary['practice_question']['question_id'] == question.id
    assert primary['answer_framework']
    assert primary['suggested_days'] in (2, 3)
    assert primary['knowledge']['title'] == '请解释依赖注入。'
    assert all(
        not task.get('knowledge')
        or task['knowledge'].get('knowledge_id') is not None
        for task in tasks
    )


def test_expression_issue_creates_separate_training_task(app):
    with app.app_context():
        question = Question.query.first()
        tasks = build_training_tasks(
            SimpleNamespace(position_code='java_backend'),
            [{
                'question_id': question.id,
                'question_type': question.type,
                'question_content': question.content,
                'final_score': 80,
                'missing_points': [],
            }],
            expression_analysis={
                'status': 'measured',
                'characters_per_minute': 360,
                'filler_rate_percent': 4.2,
                'repetition_rate_percent': 0,
            },
            limit=5,
        )

    expression_tasks = [task for task in tasks if task['category'] == 'expression']
    assert len(expression_tasks) == 1
    assert '语速偏快' in expression_tasks[0]['reason']
    assert '填充词占比' in expression_tasks[0]['reason']


def test_project_evidence_weakness_is_classified_by_content():
    weaknesses = aggregate_weaknesses([{
        'question_id': 1,
        'question_type': 'technical',
        'question_content': '解释技术原理',
        'final_score': 60,
        'missing_points': ['补充实际项目案例和量化指标'],
    }])

    assert weaknesses[0]['category'] == 'project_practice'


def test_training_material_retrieval_is_limited_and_reused(app, monkeypatch):
    calls = []

    def fake_retrieve(position_code, question_text, *_args, **_kwargs):
        calls.append((position_code, question_text))
        return [{
            'id': 99,
            'title': '依赖注入知识',
            'content': '依赖由容器创建并注入。',
            'source': 'test',
            'score': 90,
        }]

    monkeypatch.setattr(
        'app.services.recommendation_service.retrieve_knowledge',
        fake_retrieve,
    )
    with app.app_context():
        question = Question.query.filter_by(content='请解释依赖注入。').first()
        tasks = build_training_tasks(
            SimpleNamespace(position_code='java_backend'),
            [{
                'question_id': question.id,
                'question_type': question.type,
                'question_content': question.content,
                'final_score': 10,
                'missing_points': [
                    '缓存雪崩', '数据库死锁', '线程饥饿', '消息丢失',
                    '权限绕过', '日志脱敏', '接口幂等', '流量限速',
                    '内存泄漏', '延迟队列', '索引失效', '会话固定',
                ],
            }],
            expression_analysis={'status': 'not_measured'},
            limit=5,
        )

    assert len(tasks) == 5
    assert len(calls) == 1
