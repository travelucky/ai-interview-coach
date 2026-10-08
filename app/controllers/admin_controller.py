                       
import json
from datetime import datetime
from flask import Blueprint, current_app, g, request
from werkzeug.security import generate_password_hash
from app import db
from app.models import (
    User, Position, Question, Knowledge,
    InterviewSession, SystemConfig,
)
from app.models.question import QuestionType
from app.models.system_config import ConfigKey
from app.services.question_quality_service import (
    APPROVED_REVIEW_STATUSES,
    question_quality_errors,
)
from app.controllers.decorators import login_required, admin_required
from app.controllers.utils import json_ok, json_fail, get_json

bp = Blueprint('admin', __name__, url_prefix='/api/admin')
QUESTION_REVIEW_STATUSES = {
    'pending', 'in_review', 'reviewed', 'ai_reviewed', 'rejected',
}


def _admin_guard(f):
    return login_required(admin_required(f))


                               
@bp.route('/users', methods=['GET'])
@_admin_guard
def list_users():
    role = request.args.get('role')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    pagination = User.list_page(role=role, page=page, per_page=per_page)
    return json_ok({
        'users': [u.to_dict() for u in pagination.items],
        'items': [u.to_dict() for u in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
    })


@bp.route('/users', methods=['POST'])
@_admin_guard
def create_user():
    data = get_json()
    if not data or not (data.get('username') and data.get('password')):
        return json_fail('缺少 username 或 password', 400)
    username = (data.get('username') or '').strip()
    if User.get_by_username(username):
        return json_fail('用户名已存在', 400)
    role = (data.get('role') or 'user').strip() or 'user'
    if role not in ('admin', 'user'):
        role = 'user'
    user = User.create(
        username=username,
        password_hash=generate_password_hash(data['password']),
        role=role,
        display_name=(data.get('display_name') or '').strip() or None,
    )
    return json_ok(user=user.to_dict()), 201


@bp.route('/users/<int:user_id>', methods=['GET'])
@_admin_guard
def get_user(user_id):
    u = User.get_by_id(user_id)
    if not u:
        return json_fail('用户不存在', 404)
    return json_ok(user=u.to_dict())


@bp.route('/users/<int:user_id>', methods=['PUT'])
@_admin_guard
def update_user(user_id):
    data = get_json()
    if not data:
        return json_fail('请求体须为 JSON', 400)
    u = User.get_by_id(user_id)
    if not u:
        return json_fail('用户不存在', 404)
    kwargs = {}
    if 'display_name' in data:
        kwargs['display_name'] = (data.get('display_name') or '').strip() or None
    if 'role' in data and data.get('role') in ('admin', 'user'):
        kwargs['role'] = data['role']
    if data.get('password'):
        kwargs['password_hash'] = generate_password_hash(data['password'])
    if kwargs:
        User.update_by_id(user_id, **kwargs)
    u = User.get_by_id(user_id)
    return json_ok(user=u.to_dict())


@bp.route('/users/<int:user_id>', methods=['DELETE'])
@_admin_guard
def delete_user(user_id):
    if g.current_user.id == user_id:
        return json_fail('不能删除当前登录账号', 400)
    if not User.delete_by_id(user_id):
        return json_fail('用户不存在或有关联面试记录', 400)
    return json_ok(message='已删除')


                               
@bp.route('/positions', methods=['GET'])
@_admin_guard
def list_positions():
    items = Position.list_all()
    return json_ok(positions=[p.to_dict() for p in items])


@bp.route('/positions/<int:position_id>', methods=['GET'])
@_admin_guard
def get_position(position_id):
    p = Position.get_by_id(position_id)
    if not p:
        return json_fail('岗位不存在', 404)
    return json_ok(position=p.to_dict())


@bp.route('/positions', methods=['POST'])
@_admin_guard
def create_position():
    data = get_json()
    if not data or not (data.get('code') or '').strip() or not (data.get('name') or '').strip():
        return json_fail('缺少岗位编码(code)或岗位名称(name)', 400)
    code = (data.get('code') or '').strip()
    if Position.get_by_code(code):
        return json_fail('岗位编码已存在', 400)
    p = Position.create(
        code=code,
        name=(data.get('name') or '').strip(),
        description=(data.get('description') or '').strip() or None,
    )
    return json_ok(position=p.to_dict()), 201


@bp.route('/positions/<int:position_id>', methods=['PUT'])
@_admin_guard
def update_position(position_id):
    data = get_json()
    if not data:
        return json_fail('请求体须为 JSON', 400)
    p = Position.get_by_id(position_id)
    if not p:
        return json_fail('岗位不存在', 404)
    kwargs = {}
    if 'name' in data:
        kwargs['name'] = (data.get('name') or '').strip()
    if 'description' in data:
        kwargs['description'] = (data.get('description') or '').strip() or None
    if kwargs:
        Position.update_by_id(position_id, **kwargs)
    p = Position.get_by_id(position_id)
    return json_ok(position=p.to_dict())


@bp.route('/positions/<int:position_id>', methods=['DELETE'])
@_admin_guard
def delete_position(position_id):
    p = Position.get_by_id(position_id)
    if not p:
        return json_fail('岗位不存在', 404)
    if not Position.delete_by_id(position_id):
        return json_fail('该岗位下存在题目，无法删除', 400)
    return json_ok(message='已删除')


                               
@bp.route('/questions', methods=['GET'])
@_admin_guard
def list_questions():
    position_code = request.args.get('position_code')
    position_id = request.args.get('position_id', type=int)
    type_ = request.args.get('type')
    keyword = request.args.get('keyword') or request.args.get('q') or ''
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    pagination = Question.list_page(
        position_code=position_code or None,
        position_id=position_id or None,
        type_=type_ or None,
        keyword=keyword or None,
        page=page,
        per_page=per_page,
    )
    return json_ok({
        'questions': [q.to_dict() for q in pagination.items],
        'items': [q.to_dict() for q in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
    })


@bp.route('/questions/<int:question_id>', methods=['GET'])
@_admin_guard
def get_question(question_id):
    q = Question.get_by_id(question_id)
    if not q:
        return json_fail('题目不存在', 404)
    return json_ok(question=q.to_dict())


@bp.route('/questions', methods=['POST'])
@_admin_guard
def create_question():
    data = get_json()
    content = (data.get('content') or data.get('title') or '').strip()
    if not content:
        return json_fail('缺少题目内容（content）', 400)
    position_id = data.get('position_id')
    if not position_id:
        return json_fail('缺少 position_id（选题所属类目）', 400)
    position_id = int(position_id)
    if not Position.get_by_id(position_id):
        return json_fail('类目不存在', 400)
    type_ = (data.get('type') or data.get('question_type') or QuestionType.TECHNICAL).strip()
    if type_ not in (QuestionType.TECHNICAL, QuestionType.PROJECT, QuestionType.SCENARIO, QuestionType.BEHAVIORAL):
        type_ = QuestionType.TECHNICAL
    try:
        difficulty = int(data.get('difficulty') or 1)
    except (TypeError, ValueError):
        return json_fail('难度必须是 1～5 的整数', 400)
    if difficulty not in range(1, 6):
        return json_fail('难度必须是 1～5 的整数', 400)
    review_status = (data.get('review_status') or 'pending').strip()
    if review_status not in QUESTION_REVIEW_STATUSES:
        return json_fail('审核状态无效', 400)
    reviewer = (data.get('reviewer') or '').strip() or None
    if review_status == 'reviewed' and not reviewer:
        return json_fail('人工审核通过时必须填写审核人', 400)
    scoring_points = data.get('scoring_points') or []
    if review_status in APPROVED_REVIEW_STATUSES:
        quality_errors = question_quality_errors(
            content,
            (data.get('reference_answer') or '').strip(),
            scoring_points,
            type_,
        )
        if quality_errors:
            return json_fail(
                '题目尚未达到可用于正式面试的质量要求：'
                + '；'.join(quality_errors),
                400,
            )
    q = Question.create(
        position_id=position_id,
        type_=type_,
        content=content,
        reference_answer=(data.get('reference_answer') or '').strip() or None,
        difficulty=difficulty,
        tags=(data.get('tags') or '').strip() or None,
        topic=(data.get('topic') or '').strip() or None,
        scoring_points=scoring_points,
        source=(data.get('source') or 'admin').strip(),
        review_status=review_status,
        reviewer=reviewer,
        reviewed_at=datetime.utcnow() if review_status in ('reviewed', 'ai_reviewed') else None,
        content_version=1,
        is_core=bool(data.get('is_core')),
    )
    return json_ok(question=q.to_dict()), 201


@bp.route('/questions/<int:question_id>', methods=['PUT'])
@_admin_guard
def update_question(question_id):
    data = get_json()
    if not data:
        return json_fail('请求体须为 JSON', 400)
    q = Question.get_by_id(question_id)
    if not q:
        return json_fail('题目不存在', 404)
    kwargs = {}
    content_fields_changed = False
    if 'content' in data:
        kwargs['content'] = (data.get('content') or '').strip()
        if not kwargs['content']:
            return json_fail('题目内容不能为空', 400)
        content_fields_changed = kwargs['content'] != q.content
    if 'reference_answer' in data:
        kwargs['reference_answer'] = (data.get('reference_answer') or '').strip() or None
        content_fields_changed = content_fields_changed or kwargs['reference_answer'] != q.reference_answer
    if 'tags' in data:
        kwargs['tags'] = (data.get('tags') or '').strip() or None
        content_fields_changed = content_fields_changed or kwargs['tags'] != q.tags
    if 'position_id' in data:
        try:
            position_id = int(data['position_id'])
        except (TypeError, ValueError):
            return json_fail('岗位无效', 400)
        if Position.get_by_id(position_id) is None:
            return json_fail('岗位不存在', 400)
        kwargs['position_id'] = position_id
        content_fields_changed = content_fields_changed or position_id != q.position_id
    requested_type = data.get('type') or data.get('question_type')
    if requested_type and requested_type in (QuestionType.TECHNICAL, QuestionType.PROJECT, QuestionType.SCENARIO, QuestionType.BEHAVIORAL):
        kwargs['type'] = requested_type
        content_fields_changed = content_fields_changed or kwargs['type'] != q.type
    if 'difficulty' in data:
        try:
            difficulty = int(data.get('difficulty') or 1)
        except (TypeError, ValueError):
            return json_fail('难度必须是 1～5 的整数', 400)
        if difficulty not in range(1, 6):
            return json_fail('难度必须是 1～5 的整数', 400)
        kwargs['difficulty'] = difficulty
    if 'topic' in data:
        kwargs['topic'] = (data.get('topic') or '').strip() or None
        content_fields_changed = content_fields_changed or kwargs['topic'] != q.topic
    if 'scoring_points' in data:
        kwargs['scoring_points'] = json.dumps(
            data.get('scoring_points') or [],
            ensure_ascii=False,
        )
        content_fields_changed = content_fields_changed or kwargs['scoring_points'] != (q.scoring_points or '[]')
    if 'source' in data:
        kwargs['source'] = (data.get('source') or '').strip() or None
    if 'is_core' in data:
        kwargs['is_core'] = bool(data.get('is_core'))
    if 'review_status' in data:
        review_status = (data.get('review_status') or '').strip()
        if review_status not in QUESTION_REVIEW_STATUSES:
            return json_fail('审核状态无效', 400)
        reviewer = (data.get('reviewer') or '').strip() or None
        if review_status == 'reviewed' and not reviewer:
            return json_fail('人工审核通过时必须填写审核人', 400)
        kwargs['review_status'] = review_status
        kwargs['reviewer'] = reviewer
        kwargs['reviewed_at'] = (
            datetime.utcnow() if review_status in ('reviewed', 'ai_reviewed') else None
        )
    elif content_fields_changed:
        kwargs.update(
            review_status='pending',
            reviewer=None,
            reviewed_at=None,
        )
    if content_fields_changed:
        kwargs['content_version'] = max(1, int(q.content_version or 1)) + 1
    prospective_review_status = kwargs.get('review_status', q.review_status)
    if prospective_review_status in APPROVED_REVIEW_STATUSES:
        quality_errors = question_quality_errors(
            kwargs.get('content', q.content),
            kwargs.get('reference_answer', q.reference_answer),
            kwargs.get('scoring_points', q.scoring_points),
            kwargs.get('type', q.type),
        )
        if quality_errors:
            return json_fail(
                '题目尚未达到可用于正式面试的质量要求：'
                + '；'.join(quality_errors),
                400,
            )
    if kwargs:
        Question.update_by_id(question_id, **kwargs)
    q = Question.get_by_id(question_id)
    return json_ok(question=q.to_dict())


@bp.route('/questions/clear', methods=['DELETE'])
@_admin_guard
def clear_all_questions():
    rows = Question.query.filter(Question.is_active.is_(True)).all()
    for question in rows:
        question.is_active = False
        question.deleted_at = datetime.utcnow()
    db.session.commit()
    return json_ok(message='已停用全部题目，历史面试数据已保留', deleted=len(rows))


@bp.route('/questions/<int:question_id>', methods=['DELETE'])
@_admin_guard
def delete_question(question_id):
    if not Question.delete_by_id(question_id):
        return json_fail('题目不存在', 404)
    return json_ok(message='已停用该题目，历史面试数据已保留')


                                
@bp.route('/knowledge', methods=['GET'])
@_admin_guard
def list_knowledge():
    position_code = request.args.get('position_code')
    keyword = request.args.get('keyword')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    pagination = Knowledge.list_page(
        position_code=position_code or None,
        keyword=keyword or None,
        page=page,
        per_page=per_page,
    )
    return json_ok({
        'items': [k.to_dict() for k in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
    })


@bp.route('/knowledge/import', methods=['POST'])
@_admin_guard
def import_knowledge_document():
    upload = request.files.get('file') if request.files else None
    position_code = (request.form.get('position_code') or '').strip()
    source = (request.form.get('source') or 'document_import').strip()
    if upload is None or not upload.filename:
        return json_fail('请选择要导入的文件', 400)
    if not position_code or Position.get_by_code(position_code) is None:
        return json_fail('请选择有效岗位', 400)
    from app.services.knowledge_import_service import (
        KnowledgeImportError,
        MAX_DOCUMENT_BYTES,
        import_document,
    )
    data = upload.stream.read(MAX_DOCUMENT_BYTES + 1)
    try:
        result = import_document(
            data,
            upload.filename,
            position_code,
            source=source,
        )
    except KnowledgeImportError as error:
        return json_fail(str(error), 400)
    return json_ok(result=result, message='知识文档已导入'), 201


@bp.route('/knowledge/<int:knowledge_id>', methods=['GET'])
@_admin_guard
def get_knowledge(knowledge_id):
    k = Knowledge.get_by_id(knowledge_id)
    if not k:
        return json_fail('知识库条目不存在', 404)
    return json_ok(knowledge=k.to_dict())


@bp.route('/knowledge', methods=['POST'])
@_admin_guard
def create_knowledge():
    data = get_json()
    if not data or not data.get('title') or not data.get('content') or not data.get('position_code'):
        return json_fail('缺少 title、content 或 position_code', 400)
    position_code = (data['position_code'] or '').strip()
    if Position.get_by_code(position_code) is None:
        return json_fail('岗位不存在', 400)
    try:
        difficulty = int(data.get('difficulty') or 1)
    except (TypeError, ValueError):
        return json_fail('难度必须是 1～5 的整数', 400)
    if difficulty not in range(1, 6):
        return json_fail('难度必须是 1～5 的整数', 400)
    k = Knowledge.create(
        position_code=position_code,
        title=(data['title'] or '').strip(),
        content=(data.get('content') or '').strip(),
        tags=(data.get('tags') or '').strip() or None,
        topic=(data.get('topic') or '').strip() or None,
        keywords=(data.get('keywords') or '').strip() or None,
        difficulty=difficulty,
        source=(data.get('source') or 'admin').strip(),
    )
    return json_ok(knowledge=k.to_dict()), 201


@bp.route('/knowledge/<int:knowledge_id>', methods=['PUT'])
@_admin_guard
def update_knowledge(knowledge_id):
    data = get_json()
    if not data:
        return json_fail('请求体须为 JSON', 400)
    k = Knowledge.get_by_id(knowledge_id)
    if not k:
        return json_fail('知识库条目不存在', 404)
    kwargs = {}
    if 'title' in data:
        kwargs['title'] = (data.get('title') or '').strip()
    if 'content' in data:
        kwargs['content'] = (data.get('content') or '').strip()
    if 'position_code' in data:
        position_code = (data.get('position_code') or '').strip()
        if Position.get_by_code(position_code) is None:
            return json_fail('岗位不存在', 400)
        kwargs['position_code'] = position_code
    if 'tags' in data:
        kwargs['tags'] = (data.get('tags') or '').strip() or None
    if 'topic' in data:
        kwargs['topic'] = (data.get('topic') or '').strip() or None
    if 'keywords' in data:
        kwargs['keywords'] = (data.get('keywords') or '').strip() or None
    if 'difficulty' in data:
        try:
            difficulty = int(data.get('difficulty') or 1)
        except (TypeError, ValueError):
            return json_fail('难度必须是 1～5 的整数', 400)
        if difficulty not in range(1, 6):
            return json_fail('难度必须是 1～5 的整数', 400)
        kwargs['difficulty'] = difficulty
    if 'source' in data:
        kwargs['source'] = (data.get('source') or '').strip() or None
    if kwargs:
        Knowledge.update_by_id(knowledge_id, **kwargs)
    k = Knowledge.get_by_id(knowledge_id)
    return json_ok(knowledge=k.to_dict())


@bp.route('/knowledge/<int:knowledge_id>', methods=['DELETE'])
@_admin_guard
def delete_knowledge(knowledge_id):
    if not Knowledge.delete_by_id(knowledge_id):
        return json_fail('知识库条目不存在', 404)
    return json_ok(message='已删除')


@bp.route('/knowledge/embeddings/refresh', methods=['POST'])
@_admin_guard
def refresh_knowledge_embedding_index():
    from app.services.embedding_service import (
        EmbeddingServiceError,
        is_embedding_configured,
        refresh_knowledge_embeddings,
    )
    if not is_embedding_configured():
        return json_fail('Embedding 服务未完整配置', 409)
    data = get_json() or {}
    try:
        result = refresh_knowledge_embeddings(
            force=bool(data.get('force')),
            position_code=(data.get('position_code') or '').strip() or None,
        )
    except EmbeddingServiceError as error:
        return json_fail(str(error), 503)
    return json_ok(result=result, message='知识向量已更新')


                                    
@bp.route('/config', methods=['GET'])
@_admin_guard
def get_config():
    config = {
        'questions_per_session': SystemConfig.get_int(
            ConfigKey.QUESTIONS_PER_SESSION,
            current_app.config.get('QUESTIONS_PER_SESSION', 5),
        ),
        'llm_configured': bool(current_app.config.get('LLM_API_KEY')),
        'llm_api_base': current_app.config.get('LLM_API_BASE') or '',
        'llm_model': current_app.config.get('LLM_MODEL') or '',
        'asr_configured': all(
            current_app.config.get(key)
            for key in ('XFYUN_APP_ID', 'XFYUN_API_KEY', 'XFYUN_API_SECRET')
        ),
        'embedding_configured': all(
            current_app.config.get(key)
            for key in ('EMBEDDING_API_KEY', 'EMBEDDING_BASE_URL', 'EMBEDDING_MODEL')
        ),
        'embedding_model': current_app.config.get('EMBEDDING_MODEL') or '',
        'credential_source': 'environment',
    }
    return json_ok(config=config)


@bp.route('/config', methods=['PUT'])
@_admin_guard
def update_config():
    data = get_json()
    if not data:
        return json_fail('请求体须为 JSON', 400)
    if ConfigKey.QUESTIONS_PER_SESSION not in data:
        return json_fail('仅支持更新 questions_per_session；外部服务凭据由 .env 管理', 400)
    try:
        questions_per_session = int(data[ConfigKey.QUESTIONS_PER_SESSION])
    except (TypeError, ValueError):
        return json_fail('每场题目数必须为整数', 400)
    if questions_per_session < 1 or questions_per_session > 50:
        return json_fail('每场题目数必须在 1 到 50 之间', 400)
    SystemConfig.set_key_value(ConfigKey.QUESTIONS_PER_SESSION, str(questions_per_session))
    return get_config()
