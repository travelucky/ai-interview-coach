def _login_admin(client):
    response = client.post(
        '/api/auth/login',
        json={'username': 'admin', 'password': 'AdminPass123!'},
    )
    assert response.status_code == 200


def test_admin_config_never_returns_credentials(client):
    _login_admin(client)
    response = client.get('/api/admin/config')

    assert response.status_code == 200
    config = response.get_json()['config']
    assert config['credential_source'] == 'environment'
    assert 'llm_api_key' not in config
    assert 'xfyun_api_key' not in config
    assert 'xfyun_api_secret' not in config


def test_admin_can_only_update_business_config(client):
    _login_admin(client)
    response = client.put(
        '/api/admin/config',
        json={'questions_per_session': 8},
    )
    assert response.status_code == 200
    assert response.get_json()['config']['questions_per_session'] == 8

    rejected = client.put(
        '/api/admin/config',
        json={'llm_api_key': 'must-not-be-stored'},
    )
    assert rejected.status_code == 400


def test_admin_can_manage_separate_knowledge_entries(client):
    _login_admin(client)
    created = client.post('/api/admin/knowledge', json={
        'position_code': 'java_backend',
        'title': '事务隔离级别',
        'content': '隔离级别用于平衡并发一致性与性能。',
        'tags': 'MySQL,事务',
        'topic': '数据库',
        'source': 'team_review',
    })
    assert created.status_code == 201
    knowledge_id = created.get_json()['knowledge']['id']
    assert created.get_json()['knowledge']['embedding_status'] == 'missing'

    listing = client.get('/api/admin/knowledge?keyword=隔离级别')
    assert listing.status_code == 200
    assert any(item['id'] == knowledge_id for item in listing.get_json()['items'])

    updated = client.put(f'/api/admin/knowledge/{knowledge_id}', json={
        'content': '更新后的隔离级别知识。',
    })
    assert updated.status_code == 200
    assert updated.get_json()['knowledge']['embedding_status'] == 'missing'

    deleted = client.delete(f'/api/admin/knowledge/{knowledge_id}')
    assert deleted.status_code == 200


def test_admin_question_review_metadata_is_versioned(client):
    _login_admin(client)
    positions = client.get('/api/admin/positions').get_json()['positions']
    position_id = positions[0]['id']
    created = client.post('/api/admin/questions', json={
        'position_id': position_id,
        'question_type': 'scenario',
        'content': '缓存击穿时你会如何处理？',
        'reference_answer': '先识别热点键，再使用互斥重建或逻辑过期保护回源，并监控缓存命中率和数据库压力。',
        'scoring_points': [
            {
                'name': '识别热点键和击穿风险',
                'weight': 40,
                'keywords': ['热点键', '击穿'],
            },
            {
                'name': '说明重建保护和监控验证',
                'weight': 60,
                'keywords': ['互斥', '逻辑过期', '监控'],
            },
        ],
        'difficulty': 4,
        'source': 'team_review',
        'review_status': 'reviewed',
        'reviewer': 'reviewer-a',
        'is_core': True,
    })
    assert created.status_code == 201
    question = created.get_json()['question']
    assert question['review_status'] == 'reviewed'
    assert question['reviewed_at']
    assert question['content_version'] == 1
    assert question['is_core'] is True

    updated = client.put(f"/api/admin/questions/{question['id']}", json={
        'content': '缓存击穿发生时，你会如何定位、止损并修复？',
    })
    assert updated.status_code == 200
    question = updated.get_json()['question']
    assert question['review_status'] == 'pending'
    assert question['reviewer'] is None
    assert question['reviewed_at'] is None
    assert question['content_version'] == 2

    invalid = client.put(f"/api/admin/questions/{question['id']}", json={
        'review_status': 'reviewed',
        'reviewer': '',
    })
    assert invalid.status_code == 400


def test_admin_document_import_chunks_and_deduplicates_text(client):
    _login_admin(client)
    document = (
        '# Redis 缓存\n\n'
        'Redis 可以缓解数据库读压力，需要同时考虑穿透、击穿和雪崩。\n\n'
        '## 缓存更新\n\n'
        '可以使用 Cache Aside，并通过过期时间和主动失效维持一致性。'
    ).encode('utf-8')
    payload = {
        'position_code': 'java_backend',
        'source': 'team_doc',
        'file': (io.BytesIO(document), 'redis.md'),
    }
    response = client.post(
        '/api/admin/knowledge/import',
        data=payload,
        content_type='multipart/form-data',
    )
    assert response.status_code == 201
    result = response.get_json()['result']
    assert result['created'] == 2
    assert result['skipped_duplicates'] == 0

    duplicate = client.post(
        '/api/admin/knowledge/import',
        data={
            'position_code': 'java_backend',
            'source': 'team_doc',
            'file': (io.BytesIO(document), 'redis.md'),
        },
        content_type='multipart/form-data',
    )
    assert duplicate.status_code == 201
    assert duplicate.get_json()['result']['created'] == 0
    assert duplicate.get_json()['result']['skipped_duplicates'] == 2

    rejected = client.post(
        '/api/admin/knowledge/import',
        data={
            'position_code': 'java_backend',
            'file': (io.BytesIO(b'not allowed'), 'notes.exe'),
        },
        content_type='multipart/form-data',
    )
    assert rejected.status_code == 400
import io
