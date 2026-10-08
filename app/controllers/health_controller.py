from flask import Blueprint, current_app
from sqlalchemy import text

from app import db
from app.controllers.utils import json_ok
from app.models import Knowledge, Position, Question


bp = Blueprint('health', __name__, url_prefix='/api')


@bp.route('/health', methods=['GET'])
def health():
    database_ok = False
    counts = {'positions': 0, 'questions': 0, 'knowledge': 0}
    embedding_index = {'indexed': 0, 'pending': 0}
    try:
        db.session.execute(text('SELECT 1'))
        counts = {
            'positions': Position.query.count(),
            'questions': Question.query.filter(Question.is_active.is_(True)).count(),
            'knowledge': Knowledge.query.count(),
        }
        embedding_index['indexed'] = Knowledge.query.filter(
            Knowledge.embedding_vector.isnot(None),
            Knowledge.embedding_model.isnot(None),
        ).count()
        embedding_index['pending'] = max(
            0, counts['knowledge'] - embedding_index['indexed'],
        )
        database_ok = True
    except Exception:
        current_app.logger.exception('Health check failed to query the database.')
        db.session.rollback()

    llm_configured = bool(current_app.config.get('LLM_API_KEY'))
    asr_configured = all(
        current_app.config.get(key)
        for key in ('XFYUN_APP_ID', 'XFYUN_API_KEY', 'XFYUN_API_SECRET')
    )
    embedding_configured = all(
        current_app.config.get(key)
        for key in ('EMBEDDING_API_KEY', 'EMBEDDING_BASE_URL', 'EMBEDDING_MODEL')
    )
    status = 'ok' if database_ok else 'degraded'
    payload = json_ok(
        status=status,
        services={
            'database': {'status': 'ok' if database_ok else 'error'},
            'llm': {'configured': llm_configured},
            'asr': {'configured': asr_configured},
            'embedding': {
                'configured': embedding_configured,
                'model': current_app.config.get('EMBEDDING_MODEL') or None,
                **embedding_index,
            },
        },
        data=counts,
    )
    return payload, 200 if database_ok else 503
