                       
from datetime import datetime

from flask import Blueprint, g, session as browser_session
from sqlalchemy import delete
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models import (
    ExpressionMetric, InterviewMessage, InterviewReport, InterviewSession,
    Position, QuestionScore, RetrievalEvent, TrainingTask, User,
)
from app.controllers.decorators import login_required
from app.controllers.utils import json_ok, json_fail, get_json

bp = Blueprint('user', __name__, url_prefix='/api/user')


@bp.route('/profile', methods=['GET'])
@login_required
def get_profile():
    u = g.current_user
    return json_ok(user={
        'id': u.id,
        'username': u.username,
        'role': u.role,
        'display_name': u.display_name or u.username,
    })


@bp.route('/profile', methods=['PUT'])
@login_required
def update_profile():
    u = g.current_user
    data = get_json()
    if not data:
        return json_fail('请求体须为 JSON', 400)
    if 'display_name' in data:
        display_name = (data.get('display_name') or '').strip() or None
        if display_name and len(display_name) > 64:
            return json_fail('显示名称不能超过 64 个字符', 400)
        User.update_by_id(u.id, display_name=display_name)
    if data.get('password'):
        if len(data['password']) < 6:
            return json_fail('新密码至少 6 位', 400)
        User.update_by_id(u.id, password_hash=generate_password_hash(data['password']))
    u = User.get_by_id(u.id)
    return json_ok(user={
        'id': u.id,
        'username': u.username,
        'role': u.role,
        'display_name': u.display_name or u.username,
    })


@bp.route('/positions', methods=['GET'])
@login_required
def list_positions():
    items = Position.list_all()
    positions = []
    for item in items:
        payload = item.to_dict()
        # Every selectable question now passes the same reviewed quality gate,
        # so the former hard-coded Python/security Beta distinction is stale.
        payload['maturity'] = 'mvp'
        positions.append(payload)
    return json_ok(positions=positions)


@bp.route('/data-export', methods=['GET'])
@login_required
def export_personal_data():
    """Return only the authenticated user's portable, non-secret records."""
    user = g.current_user
    sessions = InterviewSession.query.filter_by(user_id=user.id).order_by(
        InterviewSession.started_at.asc()
    ).all()
    session_exports = []
    for interview in sessions:
        report = InterviewReport.get_by_session_id(interview.id)
        session_exports.append({
            'session': interview.to_dict(),
            'messages': [
                item.to_dict()
                for item in InterviewMessage.list_by_session(interview.id)
            ],
            'question_scores': [
                item.to_dict()
                for item in QuestionScore.list_by_session(interview.id)
            ],
            'expression_metrics': [
                item.to_dict()
                for item in ExpressionMetric.list_by_session(interview.id)
            ],
            'retrieval_events': [
                item.to_dict()
                for item in RetrievalEvent.list_by_session(interview.id)
            ],
            'report': report.to_dict() if report else None,
        })
    tasks = TrainingTask.query.filter_by(user_id=user.id).order_by(
        TrainingTask.id.asc()
    ).all()
    return json_ok(export={
        'export_version': '1.0',
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'profile': {
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'display_name': user.display_name or user.username,
            'created_at': user.created_at.isoformat() if user.created_at else None,
        },
        'interviews': session_exports,
        'training_tasks': [item.to_dict() for item in tasks],
        'excluded': ['password_hash', 'session_cookie', 'service_credentials'],
    })


@bp.route('/account', methods=['DELETE'])
@login_required
def delete_own_account():
    data = get_json()
    password = (data or {}).get('password') or ''
    user = g.current_user
    if not password:
        return json_fail('请输入当前密码以确认删除账号', 400)
    if not check_password_hash(user.password_hash, password):
        return json_fail('当前密码不正确', 403)

    user_id = user.id
    # Session children use ON DELETE CASCADE. Execute the parent deletion as
    # SQL so the database, rather than partially loaded ORM relationships,
    # owns the complete cleanup order.
    db.session.execute(
        delete(InterviewSession).where(InterviewSession.user_id == user_id)
    )
    db.session.execute(delete(User).where(User.id == user_id))
    db.session.commit()
    browser_session.clear()
    return json_ok(message='账号及其面试数据已删除')
