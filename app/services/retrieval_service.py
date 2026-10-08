import json
import logging
import math
import re
import time

from flask import current_app
from sqlalchemy import text

from app import db
from app.models import Knowledge


logger = logging.getLogger(__name__)
RETRIEVAL_VERSION = 'hybrid-v2'
_FTS_READY_DATABASES = set()
_SEMANTIC_FAILURE_UNTIL = {}

QUERY_ALIASES = (
    (('控制反转', '依赖装配'), 'IoC 依赖注入'),
    (('数据结构', '寻址过程'), 'HashMap 底层结构'),
    (('定义时的作用域', '记住作用域'), '闭包'),
    (('不同源', '同源策略'), '跨域 CORS'),
    (('对数复杂度', '不断折半', '已排序数组'), '二分查找'),
    (('pivot', '分区递归'), '快速排序'),
    (('最近最少使用', '淘汰的缓存'), 'LRU 缓存'),
    (('二叉树有多少层',), '二叉树最大深度'),
    (('参数化查询', '拼接 SQL'), '防止 SQL 注入'),
    (('恶意流量', '流量清洗'), 'DDoS 防御'),
    (('证书和握手', '加密通道'), 'SSL TLS HTTPS'),
    (('不默认信任', '持续验证'), '零信任'),
)

QUERY_BOILERPLATE = (
    '请使用 Python 解决',
    '说明核心思路和关键步骤',
    '分析时间与空间复杂度',
    '并指出需要处理的边界情况',
)


TYPE_DEPTH_POINTS = {
    'project': {
        'name': '说明个人职责、实施过程和可验证结果',
        'keywords': ['负责', '实施', '结果', '指标', '提升', '降低'],
    },
    'scenario': {
        'name': '说明方案取舍、异常处理和风险边界',
        'keywords': ['取舍', '异常', '风险', '降级', '应急', '边界'],
    },
    'behavioral': {
        'name': '结合真实案例说明行动、结果和复盘',
        'keywords': ['案例', '行动', '结果', '复盘', '改进'],
    },
}


def _normalize(value):
    return re.sub(r'\s+', '', (value or '').lower())


def _expand_query(value):
    source = value or ''
    normalized = source.lower()
    additions = [
        canonical for aliases, canonical in QUERY_ALIASES
        if any(alias.lower() in normalized for alias in aliases)
    ]
    return ' '.join([source] + additions), additions


def _tags(value):
    return [
        item.strip().lower()
        for item in re.split(r'[,，;；]', value or '')
        if item.strip()
    ]


def _bigrams(value):
    normalized = _normalize(value)
    return {
        normalized[index:index + 2]
        for index in range(max(0, len(normalized) - 1))
        if len(normalized[index:index + 2]) == 2
    }


def _reference_clauses(reference):
    reference = (reference or '').strip()
    if not reference:
        return []
    clauses = [
        clause.strip(' ：:。；;，,')
        for clause in re.split(r'[。；;\n]', reference)
        if clause.strip(' ：:。；;，,')
    ]
    if len(clauses) == 1 and len(clauses[0]) > 50:
        comma_parts = [
            part.strip() for part in re.split(r'[，,、]', clauses[0])
            if part.strip()
        ]
        if len(comma_parts) > 1:
            clauses = comma_parts
    if len(clauses) == 1:
        space_parts = [part.strip() for part in clauses[0].split() if part.strip()]
        if 1 < len(space_parts) <= 8:
            clauses = space_parts
    return clauses[:6]


def _point_keywords(text, tags=''):
    values = []
    values.extend(_tags(tags))
    values.extend(re.findall(r'[A-Za-z][A-Za-z0-9+#./-]{1,30}', text or ''))
    result = []
    seen = set()
    normalized_text = _normalize(text)
    for value in values:
        normalized_value = _normalize(value)
        if not normalized_value or normalized_value in seen:
            continue
        if tags and normalized_value not in normalized_text and value.lower() in _tags(tags):
            continue
        seen.add(normalized_value)
        result.append(value)
    return result[:8]


def derive_scoring_points(question):
    """Build a deterministic fallback for legacy/admin questions without points."""
    if question is None:
        return []
    clauses = _reference_clauses(getattr(question, 'reference_answer', None))
    if not clauses:
        clauses = _tags(getattr(question, 'tags', None))[:4]
    depth_point = TYPE_DEPTH_POINTS.get(getattr(question, 'type', None))
    point_specs = [
        {
            'name': clause[:80],
            'keywords': _point_keywords(clause, getattr(question, 'tags', None)),
        }
        for clause in clauses
        if clause
    ]
    if depth_point:
        point_specs.append(depth_point.copy())
    if not point_specs:
        return []
    base_weight = 100 // len(point_specs)
    remainder = 100 - base_weight * len(point_specs)
    return [
        {
            **point,
            'weight': base_weight + (1 if index < remainder else 0),
        }
        for index, point in enumerate(point_specs)
    ]


def get_effective_scoring_points(question):
    if question is None:
        return []
    configured = [
        point for point in question.get_scoring_points()
        if isinstance(point, dict) and str(point.get('name') or '').strip()
    ]
    return configured or derive_scoring_points(question)


def _relevance_score(item, question_text, user_answer, question_tags):
    query = _normalize(f'{question_text} {user_answer}')
    title = _normalize(item.title)
    score = 0.0
    if title and title == _normalize(question_text):
        score += 100.0
    elif title and (title in query or _normalize(question_text) in title):
        score += 50.0

    requested_tags = set(_tags(question_tags))
    item_tags = set(_tags(item.tags)) | set(_tags(item.keywords))
    score += len(requested_tags & item_tags) * 15.0
    score += sum(4.0 for tag in item_tags if tag and tag in query)

    query_bigrams = _bigrams(question_text)
    title_bigrams = _bigrams(item.title)
    if query_bigrams and title_bigrams:
        score += 20.0 * len(query_bigrams & title_bigrams) / len(query_bigrams)
    return score


def _ensure_fts_index():
    if db.engine.dialect.name != 'sqlite':
        return False
    database_key = str(db.engine.url)
    if database_key in _FTS_READY_DATABASES:
        return True
    try:
        connection = db.session.connection()
        connection.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
            "title, content, tags, keywords, position_code UNINDEXED, "
            "tokenize='trigram')"
        ))
        connection.execute(text(
            "CREATE TRIGGER IF NOT EXISTS knowledge_fts_insert AFTER INSERT ON knowledge BEGIN "
            "INSERT INTO knowledge_fts(rowid,title,content,tags,keywords,position_code) "
            "VALUES(new.id,new.title,new.content,coalesce(new.tags,''),coalesce(new.keywords,''),new.position_code); END"
        ))
        connection.execute(text(
            "CREATE TRIGGER IF NOT EXISTS knowledge_fts_delete AFTER DELETE ON knowledge BEGIN "
            "DELETE FROM knowledge_fts WHERE rowid=old.id; END"
        ))
        connection.execute(text(
            "CREATE TRIGGER IF NOT EXISTS knowledge_fts_update AFTER UPDATE ON knowledge BEGIN "
            "DELETE FROM knowledge_fts WHERE rowid=old.id; "
            "INSERT INTO knowledge_fts(rowid,title,content,tags,keywords,position_code) "
            "VALUES(new.id,new.title,new.content,coalesce(new.tags,''),coalesce(new.keywords,''),new.position_code); END"
        ))
        connection.execute(text(
            "INSERT OR REPLACE INTO knowledge_fts(rowid,title,content,tags,keywords,position_code) "
            "SELECT id,title,content,coalesce(tags,''),coalesce(keywords,''),position_code FROM knowledge"
        ))
        _FTS_READY_DATABASES.add(database_key)
        return True
    except Exception as error:
        logger.warning('FTS5 index unavailable; falling back to rule retrieval: %s', error)
        return False


def _fts_terms(question_text, question_tags):
    values = []
    source_text = question_text or ''
    values.extend(re.findall(r'[“"]([^”"]{2,40})[”"]', source_text))
    for boilerplate in QUERY_BOILERPLATE:
        source_text = source_text.replace(boilerplate, ' ')
    for source in (source_text, question_tags or ''):
        values.extend(re.findall(r'[\u4e00-\u9fff]{3,24}|[A-Za-z0-9+#.-]{3,32}', source))
    seen = set()
    result = []
    for value in values:
        normalized = value.lower().strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result[:12]


def _fts_rank_scores(position_code, question_text, question_tags):
    if not _ensure_fts_index():
        return {}
    terms = _fts_terms(question_text, question_tags)
    if not terms:
        return {}
    match_query = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
    try:
        rows = db.session.execute(text(
            "SELECT rowid AS id, bm25(knowledge_fts, 8.0, 1.0, 4.0, 3.0, 0.0) AS rank "
            "FROM knowledge_fts WHERE knowledge_fts MATCH :match_query "
            "AND position_code = :position_code ORDER BY rank LIMIT 50"
        ), {
            'match_query': match_query,
            'position_code': position_code,
        }).mappings().all()
    except Exception as error:
        logger.warning('FTS5 query failed; falling back to rule retrieval: %s', error)
        return {}
    return {
        row['id']: round(1.0 / (1.0 + index), 6)
        for index, row in enumerate(rows)
    }


def _cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return None
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return None
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _semantic_scores(candidates, query_text, enabled):
    if enabled is False:
        return {}, None
    try:
        from app.services.embedding_service import (
            EmbeddingServiceError,
            embed_query,
            is_embedding_configured,
            load_vector,
        )
        if not is_embedding_configured():
            return {}, None
        circuit_key = (
            current_app.config.get('EMBEDDING_BASE_URL'),
            current_app.config.get('EMBEDDING_MODEL'),
        )
        if time.monotonic() < _SEMANTIC_FAILURE_UNTIL.get(circuit_key, 0):
            return {}, None
        cached = {item.id: load_vector(item) for item in candidates}
        cached = {key: value for key, value in cached.items() if value}
        if not cached:
            return {}, None
        query_vector = embed_query(query_text)
        scores = {}
        for item_id, vector in cached.items():
            similarity = _cosine_similarity(query_vector, vector)
            if similarity is not None:
                scores[item_id] = similarity
        return scores, current_app.config.get('EMBEDDING_MODEL')
    except EmbeddingServiceError:
        logger.warning('Semantic retrieval unavailable; using lexical fallback')
        if 'circuit_key' in locals():
            _SEMANTIC_FAILURE_UNTIL[circuit_key] = time.monotonic() + 60
        return {}, None
    except Exception as error:
        logger.warning('Semantic retrieval failed; using lexical fallback: %s', error)
        if 'circuit_key' in locals():
            _SEMANTIC_FAILURE_UNTIL[circuit_key] = time.monotonic() + 60
        return {}, None


def _record_retrieval(context, position_code, question_text, results):
    if not context:
        return
    from app.models import RetrievalEvent

    methods = sorted({
        item.get('retrieval', {}).get('method') or 'none' for item in results
    })
    event = RetrievalEvent(
        session_id=context.get('session_id'),
        question_id=context.get('question_id'),
        use_case=str(context.get('use_case') or 'unknown')[:32],
        position_code=position_code,
        query_excerpt=(question_text or '')[:1000],
        retrieval_version=RETRIEVAL_VERSION,
        retrieval_method='+'.join(methods)[:32] if methods else 'none',
        results=json.dumps([
            {
                'knowledge_id': item.get('id'),
                'title': item.get('title'),
                'source': item.get('source'),
                'score': item.get('score'),
                'retrieval': item.get('retrieval'),
            }
            for item in results
        ], ensure_ascii=False),
    )
    db.session.add(event)


def retrieve_knowledge(position_code, question_text, user_answer='',
                       question_tags='', limit=3, enable_embedding=None,
                       retrieval_context=None):
    candidates = Knowledge.list_by_position(position_code)
    if not candidates:
        _record_retrieval(
            retrieval_context, position_code, question_text, [],
        )
        return []
    limit = max(1, min(10, int(limit or 3)))
    expanded_question, aliases = _expand_query(question_text)
    fts_scores = _fts_rank_scores(position_code, expanded_question, question_tags)
    semantic_query = ' '.join(filter(None, [expanded_question, question_tags, user_answer[:300]]))
    semantic_scores, embedding_model = _semantic_scores(
        candidates,
        semantic_query,
        enable_embedding,
    )
    minimum = current_app.config.get('RAG_MIN_RELEVANCE', 0.25)
    minimum_semantic = current_app.config.get('RAG_MIN_SEMANTIC_SIMILARITY', 0.52)
    ranked = []
    for item in candidates:
        rule_raw = _relevance_score(
            item, expanded_question, user_answer, question_tags,
        )
        rule_score = min(1.0, rule_raw / 100.0)
        fts_score = fts_scores.get(item.id, 0.0)
        lexical_score = max(rule_score, fts_score * 0.35)
        semantic_similarity = semantic_scores.get(item.id)
        semantic_score = (
            max(0.0, min(1.0, (semantic_similarity - 0.2) / 0.8))
            if semantic_similarity is not None else 0.0
        )
        if semantic_similarity is None:
            final_score = lexical_score
            method = 'fts5+rule' if fts_scores else 'rule'
        else:
            final_score = lexical_score * 0.30 + semantic_score * 0.70
            method = 'hybrid'
        passes_signal = lexical_score >= 0.10 or (
            semantic_similarity is not None
            and semantic_similarity >= minimum_semantic
        )
        if not passes_signal or final_score < minimum:
            continue
        signals = []
        if rule_score:
            signals.append('title_tag_or_bigram')
        if fts_score:
            signals.append('fts5_trigram_bm25')
        if semantic_similarity is not None:
            signals.append('embedding_cosine')
        if aliases:
            signals.append('controlled_query_alias')
        ranked.append({
            'item': item,
            'score': final_score,
            'method': method,
            'rule_score': rule_score,
            'fts_score': fts_score,
            'semantic_similarity': semantic_similarity,
            'signals': signals,
        })
    ranked.sort(key=lambda item: (-item['score'], item['item'].id))
    selected = []
    if ranked:
        # Do not pad an exact/high-confidence match with much weaker neighbours.
        # They add noise to scoring prompts and made the report appear to cite
        # unrelated questions merely because a caller requested three rows.
        relative_cutoff = max(minimum, ranked[0]['score'] - 0.15)
        selected = [
            row for row in ranked if row['score'] >= relative_cutoff
        ][:limit]
    results = [
        {
            'id': row['item'].id,
            'title': row['item'].title,
            'content': (row['item'].content or '')[:800],
            'tags': row['item'].tags,
            'topic': row['item'].topic,
            'source': row['item'].source,
            'score': round(row['score'] * 100, 3),
            'retrieval': {
                'version': RETRIEVAL_VERSION,
                'method': row['method'],
                'matched_signals': row['signals'],
                'rule_score': round(row['rule_score'] * 100, 3),
                'bm25_rank_score': round(row['fts_score'] * 100, 3),
                'embedding_cosine': (
                    round(row['semantic_similarity'], 6)
                    if row['semantic_similarity'] is not None else None
                ),
                'embedding_model': embedding_model,
                'minimum_relevance': minimum,
            },
        }
        for row in selected
    ]
    _record_retrieval(retrieval_context, position_code, question_text, results)
    return results


def find_missing_scoring_points(question, user_answer):
    if question is None:
        return []
    answer = _normalize(user_answer)
    answer_bigrams = _bigrams(answer)
    missing = []
    for point in get_effective_scoring_points(question):
        name = str(point.get('name') or '').strip()
        keywords = [
            _normalize(keyword)
            for keyword in point.get('keywords') or []
            if _normalize(keyword)
        ]
        keyword_hit = any(keyword in answer for keyword in keywords)
        point_bigrams = _bigrams(name)
        overlap = (
            len(answer_bigrams & point_bigrams) / len(point_bigrams)
            if point_bigrams else 0.0
        )
        if not keyword_hit and overlap < 0.18:
            missing.append(point)
    return missing
