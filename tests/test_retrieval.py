from app import db
from app.models import Question, RetrievalEvent
from app.services.followup_service import decide_followup_or_next
from app.services.retrieval_service import (
    get_effective_scoring_points,
    find_missing_scoring_points,
    retrieve_knowledge,
)


def test_retrieval_prefers_exact_question_knowledge(app):
    with app.app_context():
        results = retrieve_knowledge(
            'java_backend',
            '请解释依赖注入。',
            user_answer='容器会管理对象。',
            question_tags='Spring',
            limit=3,
        )

    assert results
    assert results[0]['title'] == '请解释依赖注入。'
    assert results[0]['source'] == 'test_seed'
    assert results[0]['retrieval']['version'] == 'hybrid-v2'


def test_irrelevant_query_returns_empty_instead_of_arbitrary_rows(app):
    with app.app_context():
        results = retrieve_knowledge(
            'java_backend',
            '红烧肉需要加多少糖？',
            enable_embedding=False,
        )

    assert results == []


def test_retrieval_trace_records_sources_scores_and_use_case(app):
    with app.app_context():
        results = retrieve_knowledge(
            'java_backend',
            '请解释依赖注入。',
            question_tags='Spring',
            enable_embedding=False,
            retrieval_context={
                'question_id': Question.query.filter_by(
                    content='请解释依赖注入。'
                ).first().id,
                'use_case': 'test',
            },
        )
        db.session.commit()
        event = RetrievalEvent.query.one()
        payload = event.to_dict()

    assert results
    assert payload['use_case'] == 'test'
    assert payload['retrieval_version'] == 'hybrid-v2'
    assert payload['results'][0]['knowledge_id'] == results[0]['id']
    assert payload['results'][0]['source'] == 'test_seed'


def test_semantic_failure_falls_back_to_lexical_result(app, monkeypatch):
    from app.models import Knowledge
    from app.services.embedding_service import EmbeddingServiceError

    with app.app_context():
        item = Knowledge.query.one()
        app.config.update(
            EMBEDDING_API_KEY='test-key',
            EMBEDDING_BASE_URL='https://example.invalid/v1',
            EMBEDDING_MODEL='test-model',
        )
        item.embedding_model = 'test-model'
        from app.services.embedding_service import embedding_content_hash
        item.content_hash = embedding_content_hash(item)
        item.embedding_vector = '[1.0,0.0]'
        db.session.commit()
        monkeypatch.setattr(
            'app.services.embedding_service.embed_query',
            lambda _text: (_ for _ in ()).throw(EmbeddingServiceError('offline')),
        )
        results = retrieve_knowledge(
            'java_backend',
            '请解释依赖注入。',
        )

    assert results
    assert results[0]['retrieval']['method'] in {'fts5+rule', 'rule'}


def test_missing_scoring_points_are_detected(app):
    with app.app_context():
        question = Question.query.filter_by(content='请解释依赖注入。').first()
        missing = find_missing_scoring_points(question, '我只知道这是 Spring 的功能。')
        covered = find_missing_scoring_points(question, '这里需要说明核心原理。')

    assert missing[0]['name'] == '说明核心原理'
    assert covered == []


def test_followup_uses_missing_point_without_llm(app):
    with app.app_context():
        question = Question.query.filter_by(content='请解释依赖注入。').first()
        action, content = decide_followup_or_next(
            question.content,
            '我暂时只知道它属于 Spring。',
            follow_ups_this_question=0,
            next_question_content='下一题',
            position_code='java_backend',
            question=question,
        )

    assert action == 'follow_up'
    assert '说明核心原理' in content


def test_legacy_question_derives_points_from_reference_answer(app):
    with app.app_context():
        question = Question(
            position_id=1,
            type='technical',
            content='如何防御 DDoS 攻击？',
            reference_answer='流量清洗 CDN 限流',
            scoring_points='[]',
        )
        points = get_effective_scoring_points(question)
        missing = find_missing_scoring_points(question, '可以使用 CDN 隐藏源站。')

    assert [point['name'] for point in points] == ['流量清洗', 'CDN', '限流']
    assert [point['name'] for point in missing] == ['流量清洗', '限流']


def test_long_scenario_answer_gets_depth_followup_without_llm(app):
    with app.app_context():
        question = Question(
            position_id=1,
            type='scenario',
            content='如何保护用户密码安全？',
            reference_answer='使用哈希和盐值保存密码',
            scoring_points='[]',
        )
        answer = (
            '系统使用带独立盐值的密码哈希算法保存密码，并设置登录限速、多因素认证和异常告警。'
            '同时制定密码轮换、泄露响应和审计流程，避免保存任何明文或者可逆密文。'
        )
        action, content = decide_followup_or_next(
            question.content,
            answer * 2,
            follow_ups_this_question=0,
            next_question_content='下一题',
            position_code='web_sec',
            question=question,
        )

    assert action == 'follow_up'
    assert '取舍' in content
