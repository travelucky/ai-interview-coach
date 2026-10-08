                       
import os
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

db = SQLAlchemy()


@event.listens_for(Engine, 'connect')
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """SQLite disables foreign-key enforcement unless each connection enables it."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute('PRAGMA foreign_keys=ON')
    cursor.close()


def create_app(config_name=None, config_overrides=None):
    if config_name is None:
        config_name = os.environ.get('APP_ENV', 'development')
    from config import config_by_name
    if config_name not in config_by_name:
        raise ValueError(f'Unknown application environment: {config_name}')

    project_root = Path(__file__).resolve().parent.parent
    instance_path = project_root / 'instance'
    instance_path.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, instance_path=str(instance_path))
    app.config.from_object(config_by_name[config_name])
    if config_overrides:
        app.config.update(config_overrides)
    app.config.setdefault('JSON_AS_ASCII', False)

    @app.before_request
    def _enforce_same_origin_for_writes():
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return None
        origin = (request.headers.get('Origin') or '').rstrip('/')
        if not origin:
            return None
        allowed = {request.host_url.rstrip('/')}
        allowed.update(app.config.get('TRUSTED_ORIGINS') or ())
        if origin not in allowed:
            return jsonify(success=False, message='请求来源不受信任'), 403
        return None

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        response.headers.setdefault(
            'Permissions-Policy',
            'camera=(), geolocation=(), microphone=(self)',
        )
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'",
        )
        response.headers.setdefault('Cache-Control', 'no-store')
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def _payload_too_large(_error):
        return jsonify(
            success=False,
            message='请求内容过大，请缩小文件或回答后重试',
            error={
                'code': 'payload_too_large',
                'message': '请求内容过大，请缩小文件或回答后重试',
            },
        ), 413

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if not request.path.startswith('/api/'):
            return error
        message = '接口不存在' if error.code == 404 else error.description
        return jsonify(
            success=False,
            message=message,
            error={'code': error.name.lower().replace(' ', '_'), 'message': message},
        ), error.code

    @app.errorhandler(Exception)
    def _unexpected_error(error):
        if not request.path.startswith('/api/'):
            raise error
        # Log exception type and stack only; never serialize request bodies,
        # cookies, authorization headers, passwords, answers, or API keys.
        app.logger.exception('Unhandled API error on %s %s', request.method, request.path)
        return jsonify(
            success=False,
            message='服务器处理失败，请稍后重试',
            error={
                'code': 'internal_error',
                'message': '服务器处理失败，请稍后重试',
            },
        ), 500

    if config_name == 'production' and app.config.get('SECRET_KEY_IS_EPHEMERAL'):
        raise RuntimeError('Production requires FLASK_SECRET_KEY to be set.')
    if app.config.get('SECRET_KEY_IS_EPHEMERAL'):
        app.logger.warning('FLASK_SECRET_KEY is not set; sessions will reset after restart.')

    db.init_app(app)
    from app.controllers import register_blueprints
    from app.views import bp as views_bp
    register_blueprints(app)
    app.register_blueprint(views_bp)

    with app.app_context():
                               
        from app.models import (              
            user,
            position,
            question,
            knowledge,
            interview_session,
            interview_message,
            interview_report,
            system_config,
            question_score,
            expression_metric,
            retrieval_event,
            training_task,
        )
                                                  
                         

    return app
