import hashlib
import json
import logging
import math
from datetime import datetime

from flask import current_app

from app import db
from app.models import Knowledge


logger = logging.getLogger(__name__)
_QUERY_VECTOR_CACHE = {}


class EmbeddingServiceError(RuntimeError):
    pass


def is_embedding_configured():
    return all((current_app.config.get(key) or '').strip() for key in (
        'EMBEDDING_API_KEY', 'EMBEDDING_BASE_URL', 'EMBEDDING_MODEL',
    ))


def knowledge_embedding_text(item):
    return '\n'.join(filter(None, [
        f'岗位：{item.position_code}',
        f'标题：{item.title}',
        f'主题：{item.topic or ""}',
        f'标签：{item.tags or ""}',
        f'关键词：{item.keywords or ""}',
        f'内容：{item.content}',
    ]))


def embedding_content_hash(item):
    return hashlib.sha256(
        knowledge_embedding_text(item).encode('utf-8')
    ).hexdigest()


def _validate_vector(value):
    if not isinstance(value, list) or not value or len(value) > 65536:
        raise EmbeddingServiceError('Embedding 服务返回了无效向量')
    vector = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise EmbeddingServiceError('Embedding 向量包含非数值分量')
        component = float(component)
        if not math.isfinite(component):
            raise EmbeddingServiceError('Embedding 向量包含非有限数')
        vector.append(component)
    return vector


def embed_texts(texts):
    texts = [str(text or '').strip() for text in texts]
    if not texts or any(not text for text in texts):
        raise EmbeddingServiceError('Embedding 输入不能为空')
    if not is_embedding_configured():
        raise EmbeddingServiceError('Embedding 服务未完整配置')
    import requests

    base_url = current_app.config['EMBEDDING_BASE_URL'].rstrip('/')
    url = base_url if base_url.endswith('/embeddings') else base_url + '/embeddings'
    try:
        # The request has an explicit, bounded timeout from validated config.
        response = requests.post(  # nosec B113
            url,
            headers={
                'Authorization': 'Bearer ' + current_app.config['EMBEDDING_API_KEY'],
                'Content-Type': 'application/json',
            },
            json={
                'model': current_app.config['EMBEDDING_MODEL'],
                'input': texts,
                'encoding_format': 'float',
            },
            timeout=current_app.config.get('EMBEDDING_TIMEOUT_SECONDS', 30),
        )
        response.raise_for_status()
        rows = response.json().get('data') or []
    except Exception as error:
        logger.warning('Embedding request failed: %s', error)
        raise EmbeddingServiceError('Embedding 服务请求失败') from error
    rows = sorted(rows, key=lambda row: row.get('index', 0))
    if len(rows) != len(texts):
        raise EmbeddingServiceError('Embedding 服务返回数量与输入不一致')
    vectors = [_validate_vector(row.get('embedding')) for row in rows]
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise EmbeddingServiceError('Embedding 向量维度不一致')
    return vectors


def embed_query(text):
    model = current_app.config.get('EMBEDDING_MODEL') or ''
    cache_key = (model, hashlib.sha256(text.encode('utf-8')).hexdigest())
    cached = _QUERY_VECTOR_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    vector = embed_texts([text])[0]
    if len(_QUERY_VECTOR_CACHE) >= 128:
        _QUERY_VECTOR_CACHE.pop(next(iter(_QUERY_VECTOR_CACHE)))
    _QUERY_VECTOR_CACHE[cache_key] = tuple(vector)
    return vector


def refresh_knowledge_embeddings(force=False, position_code=None):
    query = Knowledge.query
    if position_code:
        query = query.filter_by(position_code=position_code)
    model = current_app.config.get('EMBEDDING_MODEL') or ''
    pending = []
    for item in query.order_by(Knowledge.id.asc()).all():
        content_hash = embedding_content_hash(item)
        if not force and item.embedding_vector and item.embedding_model == model and item.content_hash == content_hash:
            continue
        pending.append((item, content_hash))

    batch_size = current_app.config.get('EMBEDDING_BATCH_SIZE', 32)
    updated = 0
    dimension = None
    try:
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            vectors = embed_texts([knowledge_embedding_text(item) for item, _hash in batch])
            for (item, content_hash), vector in zip(batch, vectors):
                item.content_hash = content_hash
                item.embedding_model = model
                item.embedding_vector = json.dumps(vector, separators=(',', ':'))
                item.embedding_updated_at = datetime.utcnow()
                updated += 1
                dimension = len(vector)
            db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {
        'updated': updated,
        'skipped': query.count() - updated,
        'model': model,
        'dimension': dimension,
    }


def load_vector(item):
    if item.embedding_model != (current_app.config.get('EMBEDDING_MODEL') or ''):
        return None
    if item.content_hash != embedding_content_hash(item):
        return None
    try:
        return _validate_vector(json.loads(item.embedding_vector or ''))
    except (TypeError, ValueError, EmbeddingServiceError):
        return None
