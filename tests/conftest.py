import json

import pytest
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Knowledge, Position, Question, SystemConfig, User
from app.models.question import QuestionType


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / 'test.db'
    application = create_app(
        'testing',
        {
            'SECRET_KEY': 'test-secret-key',
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
        position = Position(
            code='java_backend',
            name='Java 后端开发',
            description='测试岗位',
        )
        db.session.add(position)
        db.session.flush()
        question_specs = [
            (QuestionType.TECHNICAL, '请解释依赖注入。'),
            (QuestionType.TECHNICAL, '请解释 Spring AOP。'),
            (QuestionType.PROJECT, '介绍一个你负责的后端项目。'),
            (QuestionType.SCENARIO, '如何处理接口突发流量？'),
            (QuestionType.BEHAVIORAL, '遇到项目冲突时你如何处理？'),
        ]
        for question_type, content in question_specs:
            db.session.add(
                Question(
                    position_id=position.id,
                    type=question_type,
                    content=content,
                    reference_answer='说明核心原理、关键步骤、适用场景以及必要的边界条件。',
                    difficulty=1,
                    tags='测试',
                    topic='测试主题',
                    scoring_points=json.dumps(
                        [
                            {
                                'name': '说明核心原理',
                                'weight': 60,
                                'keywords': ['核心原理'],
                            },
                            {
                                'name': '结合核心原理说明场景和边界',
                                'weight': 40,
                                'keywords': ['核心原理', '原理'],
                            },
                        ],
                        ensure_ascii=False,
                    ),
                    review_status='ai_reviewed',
                    reviewer='test-reviewer',
                )
            )
        db.session.add(
            Knowledge(
                position_code='java_backend',
                title='请解释依赖注入。',
                content='依赖注入由容器负责对象创建和依赖装配。',
                tags='测试,Spring',
                topic='Spring',
                keywords='依赖注入,Spring',
                difficulty=1,
                source='test_seed',
            )
        )
        db.session.add(
            User(
                username='admin',
                password_hash=generate_password_hash('AdminPass123!'),
                role='admin',
                display_name='测试管理员',
            )
        )
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def registered_client(client):
    response = client.post(
        '/api/auth/register',
        json={
            'username': 'candidate',
            'password': 'Candidate123!',
            'confirm_password': 'Candidate123!',
            'display_name': '候选人',
        },
    )
    assert response.status_code == 201
    response = client.post(
        '/api/auth/login',
        json={'username': 'candidate', 'password': 'Candidate123!'},
    )
    assert response.status_code == 200
    return client
