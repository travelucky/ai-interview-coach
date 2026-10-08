                       
import threading
import time
from collections import defaultdict, deque

from flask import Blueprint, current_app, session, request
from werkzeug.security import check_password_hash, generate_password_hash
from app.models import User
from app.controllers.utils import json_ok, json_fail, get_json

bp = Blueprint('auth', __name__, url_prefix='/api/auth')
_LOGIN_FAILURES = defaultdict(deque)
_LOGIN_FAILURES_LOCK = threading.Lock()


def _login_attempt_key(username):
    return (
        current_app.config.get('SQLALCHEMY_DATABASE_URI'),
        request.remote_addr or 'unknown',
        username.lower(),
    )


def _failed_login_limited(key):
    now = time.monotonic()
    window = current_app.config.get('LOGIN_FAILURE_WINDOW_SECONDS', 300)
    maximum = current_app.config.get('LOGIN_MAX_FAILURES', 5)
    with _LOGIN_FAILURES_LOCK:
        attempts = _LOGIN_FAILURES[key]
        while attempts and attempts[0] <= now - window:
            attempts.popleft()
        return len(attempts) >= maximum


def _record_login_failure(key):
    with _LOGIN_FAILURES_LOCK:
        _LOGIN_FAILURES[key].append(time.monotonic())


def _clear_login_failures(key):
    with _LOGIN_FAILURES_LOCK:
        _LOGIN_FAILURES.pop(key, None)


@bp.route('/login', methods=['POST'])
def login():
    data = get_json()
    if not data:
        return json_fail('请求体须为 JSON', 400)
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if len(password) > 128:
        return json_fail('用户名或密码错误', 401)
    if not username or not password:
        return json_fail('用户名与密码不能为空', 400)
    attempt_key = _login_attempt_key(username)
    if _failed_login_limited(attempt_key):
        return json_fail('登录失败次数过多，请稍后再试', 429)
    user = User.get_by_username(username)
    if not user or not check_password_hash(user.password_hash, password):
        _record_login_failure(attempt_key)
        return json_fail('用户名或密码错误', 401)
    _clear_login_failures(attempt_key)
    session.clear()
    session['user_id'] = user.id
    session.permanent = True
    return json_ok(user={'id': user.id, 'username': user.username, 'role': user.role, 'display_name': user.display_name or user.username})


@bp.route('/register', methods=['POST'])
def register():
    data = get_json()
    if not data:
        return json_fail('请求体须为 JSON', 400)
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    confirm_password = data.get('confirm_password') or data.get('confirm') or ''
    display_name = (data.get('display_name') or '').strip() or None

    if not username:
        return json_fail('用户名不能为空', 400)
    if len(username) < 3 or len(username) > 64:
        return json_fail('用户名长度需为 3-64', 400)
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+', username):
        return json_fail('用户名仅支持字母/数字/下划线/短横线', 400)
    if not password:
        return json_fail('密码不能为空', 400)
    if len(password) < 8 or len(password) > 128:
        return json_fail('密码长度需为 8-128 位', 400)
    if confirm_password and password != confirm_password:
        return json_fail('两次密码不一致', 400)
    if User.get_by_username(username):
        return json_fail('用户名已存在', 400)
    if display_name and len(display_name) > 64:
        return json_fail('显示名称不能超过 64 位', 400)

    user = User.create(
        username=username,
        password_hash=generate_password_hash(password),
        role='user',
        display_name=display_name,
    )
    return json_ok(user={'id': user.id, 'username': user.username, 'role': user.role, 'display_name': user.display_name or user.username}), 201


@bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return json_ok(message='已登出')
