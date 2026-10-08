import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / 'seed'
sys.path.insert(0, str(ROOT))

from app import create_app, db  # noqa: E402
from app.models import Knowledge, Position, Question, SystemConfig, User  # noqa: E402
from app.migrations import ensure_mvp_schema  # noqa: E402
from app.services.question_quality_service import is_question_interview_ready  # noqa: E402


def _read_seed(name):
    path = SEED_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f'Seed file not found: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def _normalized_seed_difficulty(item):
    """Map legacy all-L1 imports onto the documented 1-5 difficulty scale."""
    configured = int(item.get('difficulty') or 1)
    source = (item.get('source') or '').strip()
    if configured != 1 or (source and source != 'legacy_seed'):
        return max(1, min(5, configured))
    question_type = item.get('type')
    content = item.get('legacy_content') or item.get('content') or ''
    if question_type == 'scenario':
        return 4
    if question_type == 'project':
        return 3
    if question_type == 'behavioral':
        return 2
    if any(word in content for word in ('系统设计', '架构', '高并发', '优化', '安全方案')):
        return 4
    if any(word in content for word in ('LFU', '正则表达式', '最短路径', '并查集', 'Kruskal', 'Prim', 'KMP', 'N皇后', '全排列')):
        return 5
    if any(word in content for word in ('LRU', '动态规划', '二叉树', '图', '回溯', 'Trie', '编辑距离', '最长')):
        return 4
    if any(word in content for word in ('如何实现', '底层原理', '复杂度', '机制', '区别', '流程')):
        return 3
    if '实现' in content or any(word in content for word in ('排序', '查找', '链表', '矩阵')):
        return 3
    if any(word in content for word in ('如何', '为什么', '作用', '优缺点')):
        return 2
    if any(word in content for word in ('判断', '找到', '寻找', '反转', '删除', '合并', '计算')):
        return 2
    return 1


def _mark_core_review_candidates(positions, target_per_position=30):
    quotas = {'technical': 18, 'project': 4, 'scenario': 4, 'behavioral': 4}
    for position in positions.values():
        rows = Question.query.filter_by(position_id=position.id, is_active=True).all()
        for row in rows:
            # Explicit curated choices remain core; legacy candidates are rebuilt
            # deterministically so repeated seed imports are idempotent.
            if row.source == 'legacy_seed':
                row.is_core = False
            if not is_question_interview_ready(row):
                row.is_core = False

        ready_rows = [row for row in rows if is_question_interview_ready(row)]
        selected = [row for row in ready_rows if row.is_core]
        selected_ids = {row.id for row in selected}

        def quality(row):
            return (
                len(row.get_scoring_points()) >= 2,
                bool(row.reference_answer and len(row.reference_answer) >= 30),
                row.difficulty in (2, 3, 4),
                bool(row.topic and row.topic != '技术基础'),
                -row.id,
            )

        for question_type, quota in quotas.items():
            already = sum(row.type == question_type for row in selected)
            candidates = sorted(
                [
                    row for row in ready_rows
                    if row.type == question_type and row.id not in selected_ids
                ],
                key=quality,
                reverse=True,
            )
            for row in candidates[:max(0, quota - already)]:
                row.is_core = True
                selected.append(row)
                selected_ids.add(row.id)

        if len(selected) < target_per_position:
            candidates = sorted(
                [row for row in ready_rows if row.id not in selected_ids],
                key=quality,
                reverse=True,
            )
            for row in candidates[:target_per_position - len(selected)]:
                row.is_core = True
    db.session.commit()


def seed_positions():
    created = 0
    updated = 0
    for item in _read_seed('positions.json'):
        code = (item.get('code') or '').strip()
        name = (item.get('name') or '').strip()
        if not code or not name:
            continue
        row = Position.get_by_code(code)
        if row is None:
            db.session.add(
                Position(
                    code=code,
                    name=name,
                    description=item.get('description'),
                )
            )
            created += 1
        else:
            row.name = name
            row.description = item.get('description')
            updated += 1
    db.session.commit()
    return created, updated


def seed_questions():
    created = 0
    updated = 0
    positions = {row.code: row for row in Position.query.all()}
    items = _read_seed('questions.json')
    curated_path = SEED_DIR / 'questions_curated.json'
    if curated_path.is_file():
        items.extend(_read_seed('questions_curated.json'))
    for item in items:
        position = positions.get((item.get('position_code') or '').strip())
        content = (item.get('content') or '').strip()
        question_type = (item.get('type') or '').strip()
        if position is None or not content or not question_type:
            continue
        row = Question.query.filter_by(
            position_id=position.id,
            type=question_type,
            content=content,
        ).first()
        legacy_contents = item.get('legacy_contents') or []
        if item.get('legacy_content'):
            legacy_contents = [item.get('legacy_content')] + list(legacy_contents)
        if row is None:
            for legacy_content in legacy_contents:
                legacy_content = (legacy_content or '').strip()
                if not legacy_content:
                    continue
                row = Question.query.filter_by(
                    position_id=position.id,
                    type=question_type,
                    content=legacy_content,
                ).first()
                if row is not None:
                    break
        values = {
            'reference_answer': item.get('reference_answer'),
            'difficulty': _normalized_seed_difficulty(item),
            'tags': item.get('tags'),
            'topic': item.get('topic'),
            'scoring_points': json.dumps(
                item.get('scoring_points') or [],
                ensure_ascii=False,
            ),
            'is_active': True,
            'deleted_at': None,
            'source': item.get('source') or 'legacy_seed',
            'review_status': item.get('review_status') or 'pending',
            'reviewer': item.get('reviewer'),
            'reviewed_at': (
                datetime.fromisoformat(item['reviewed_at'])
                if item.get('reviewed_at') else None
            ),
            'content_version': max(1, int(item.get('content_version') or 1)),
            'is_core': bool(item.get('is_core')),
        }
        if row is None:
            db.session.add(
                Question(
                    position_id=position.id,
                    type=question_type,
                    content=content,
                    **values,
                )
            )
            created += 1
        else:
            row.content = content
            for key, value in values.items():
                setattr(row, key, value)
            updated += 1
    db.session.commit()
    _mark_core_review_candidates(positions)
    return created, updated


def seed_knowledge():
    created = 0
    updated = 0
    for item in _read_seed('knowledge.json'):
        position_code = (item.get('position_code') or '').strip()
        title = (item.get('title') or '').strip()
        content = (item.get('content') or '').strip()
        if not position_code or not title or not content:
            continue
        row = Knowledge.query.filter_by(
            position_code=position_code,
            title=title,
        ).first()
        legacy_titles = item.get('legacy_titles') or []
        if item.get('legacy_title'):
            legacy_titles = [item.get('legacy_title')] + list(legacy_titles)
        if row is None:
            for legacy_title in legacy_titles:
                legacy_title = (legacy_title or '').strip()
                if not legacy_title:
                    continue
                row = Knowledge.query.filter_by(
                    position_code=position_code,
                    title=legacy_title,
                ).first()
                if row is not None:
                    break
        if row is None:
            db.session.add(
                Knowledge(
                    position_code=position_code,
                    title=title,
                    content=content,
                    tags=item.get('tags'),
                    topic=item.get('topic'),
                    keywords=item.get('keywords'),
                    difficulty=item.get('difficulty') or 1,
                    source=item.get('source'),
                )
            )
            created += 1
        else:
            row.title = title
            row.content = content
            row.tags = item.get('tags')
            row.topic = item.get('topic')
            row.keywords = item.get('keywords')
            row.difficulty = item.get('difficulty') or 1
            row.source = item.get('source')
            row.content_hash = None
            row.embedding_model = None
            row.embedding_vector = None
            row.embedding_updated_at = None
            updated += 1
    db.session.commit()
    return created, updated


def create_demo_admin():
    username = (os.environ.get('DEMO_ADMIN_USERNAME') or 'admin').strip()
    password = os.environ.get('DEMO_ADMIN_PASSWORD') or ''
    if len(password) < 8:
        raise ValueError(
            'DEMO_ADMIN_PASSWORD must contain at least 8 characters when '
            '--create-admin is used.'
        )
    user = User.get_by_username(username)
    if user is None:
        db.session.add(
            User(
                username=username,
                password_hash=generate_password_hash(password),
                role='admin',
                display_name='管理员',
            )
        )
        action = 'created'
    else:
        user.password_hash = generate_password_hash(password)
        user.role = 'admin'
        action = 'updated'
    db.session.commit()
    return username, action


def init_db(load_seed=False, create_admin=False):
    app = create_app()
    with app.app_context():
        db.create_all()
        applied_columns = ensure_mvp_schema()
        SystemConfig.seed_defaults()
        print(f'Database initialized: {app.config["SQLALCHEMY_DATABASE_URI"]}')
        if applied_columns:
            print('Applied database columns: ' + ', '.join(applied_columns))

        if load_seed:
            position_result = seed_positions()
            question_result = seed_questions()
            knowledge_result = seed_knowledge()
            print(
                'Seed import complete: '
                f'positions +{position_result[0]}/~{position_result[1]}, '
                f'questions +{question_result[0]}/~{question_result[1]}, '
                f'knowledge +{knowledge_result[0]}/~{knowledge_result[1]}.'
            )

        if create_admin:
            username, action = create_demo_admin()
            print(f'Demo administrator {action}: {username}')


def main():
    parser = argparse.ArgumentParser(description='Initialize the application database.')
    parser.add_argument('--seed', action='store_true', help='Import JSON seed data.')
    parser.add_argument(
        '--create-admin',
        action='store_true',
        help='Create or update the demo administrator from environment variables.',
    )
    args = parser.parse_args()
    init_db(load_seed=args.seed, create_admin=args.create_admin)


if __name__ == '__main__':
    main()
