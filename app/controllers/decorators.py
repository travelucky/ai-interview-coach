                       
from functools import wraps
from flask import session, jsonify
from app.models import User


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify(success=False, message='未登录'), 401
        user = User.get_by_id(user_id)
        if not user:
            session.clear()
            return jsonify(success=False, message='用户不存在'), 401
        from flask import g
        g.current_user = user
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        from flask import g
        user = getattr(g, 'current_user', None)
        if not user:
            return jsonify(success=False, message='未登录'), 401
        if user.role != 'admin':
            return jsonify(success=False, message='需要管理员权限'), 403
        return f(*args, **kwargs)
    return wrapped
